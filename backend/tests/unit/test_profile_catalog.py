"""Presentation catalog rules for the creator detail page (offline, no database)."""

from pathlib import Path

from xingtu.contracts import PlatformRegistry
from xingtu.profile_catalog import DISPLAY_NAME_CORRECTIONS, build_profile_field_catalog


def live_registry() -> PlatformRegistry:
    root = Path(__file__).resolve().parents[3]
    return PlatformRegistry.model_validate_json(
        (root / "contracts/douyin_xingtu.verified.json").read_text()
    )


def test_catalog_covers_every_registered_profile_field():
    registry = live_registry()
    catalog = build_profile_field_catalog(registry)

    assert catalog.contract_version == registry.contract_version
    assert [module.key for module in catalog.modules] == [m.key for m in registry.modules]
    registered = [(m.key, f.key) for m in registry.modules for f in m.fields]
    assert len(registered) == 81
    served = [(m.key, f.key) for m in catalog.modules for f in m.fields]
    assert served == registered


def test_every_catalog_entry_has_a_display_name_and_contract_name():
    catalog = build_profile_field_catalog(live_registry())
    for module in catalog.modules:
        for field in module.fields:
            assert field.name.strip()
            assert field.contract_name.strip()
            assert field.kind


def test_registered_unit_and_period_are_carried_through():
    catalog = build_profile_field_catalog(live_registry())
    fields = {(m.key, f.key): f for m in catalog.modules for f in m.fields}

    followers = fields[("basic", "followers")]
    assert followers.unit == "count"
    assert followers.period_label is None

    growth = fields[("basic", "monthly_follower_growth_rate")]
    assert growth.kind == "ratio"
    assert growth.unit == "ratio"
    assert growth.period_label == "月"

    connected = fields[("fans", "monthly_connected_users")]
    assert connected.kind == "number"
    assert connected.period_label == "月"


def test_registered_empty_and_absence_semantics_are_exposed():
    catalog = build_profile_field_catalog(live_registry())
    fields = {(m.key, f.key): f for m in catalog.modules for f in m.fields}

    # Registered dash values are exactly the ones the platform uses for "present but empty".
    assert fields[("basic", "introduction")].empty_values == ["", "--", "—"]
    # `play_median` is registered as "an absent response path is known platform NO_DATA".
    assert fields[("spread", "play_median")].missing_source_status == "NO_DATA"


def test_follower_fields_carry_the_evidence_corrected_display_name():
    catalog = build_profile_field_catalog(live_registry())
    fields = {(m.key, f.key): f for m in catalog.modules for f in m.fields}

    for module_key, field_key in DISPLAY_NAME_CORRECTIONS:
        field = fields[(module_key, field_key)]
        assert field.name_source == "evidence_correction"
        assert field.name != field.contract_name
        assert field.name == DISPLAY_NAME_CORRECTIONS[(module_key, field_key)]

    # The correction never leaks into other fields: `connection_daily_trend` keeps its name.
    untouched = fields[("fans", "connection_daily_trend")]
    assert untouched.name_source == "contract"
    assert untouched.name == untouched.contract_name


def test_fields_without_a_correction_keep_the_registered_name():
    catalog = build_profile_field_catalog(live_registry())
    corrected = set(DISPLAY_NAME_CORRECTIONS)
    for module in catalog.modules:
        for field in module.fields:
            if (module.key, field.key) in corrected:
                continue
            assert field.name_source == "contract"
            assert field.name == field.contract_name
