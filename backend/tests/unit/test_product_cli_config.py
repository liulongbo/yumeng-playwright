from pathlib import Path
from types import SimpleNamespace

import pytest
from xingtu import product_cli
from xingtu.domain import CollectorError
from xingtu.product_cli import resolve_intake_config


def test_cloud_intake_config_does_not_require_unit_config(monkeypatch):
    monkeypatch.delenv("XINGTU_DEFAULT_EXECUTION_UNIT_ID", raising=False)
    registry = Path("contracts/douyin_xingtu.verified.json")

    assert resolve_intake_config(None, "unit-mac-cell-01", registry) == (
        "unit-mac-cell-01",
        registry,
    )


def test_cloud_intake_config_requires_an_explicit_default_unit(monkeypatch):
    monkeypatch.delenv("XINGTU_DEFAULT_EXECUTION_UNIT_ID", raising=False)

    with pytest.raises(CollectorError, match="DEFAULT_EXECUTION_UNIT_ID_REQUIRED"):
        resolve_intake_config(None, None, Path("contracts/douyin_xingtu.verified.json"))


def test_legacy_unit_config_remains_supported(monkeypatch):
    registry = Path("contracts/douyin_xingtu.verified.json")
    monkeypatch.setattr(
        product_cli,
        "load_unit",
        lambda path: SimpleNamespace(unit_id="legacy-unit", registry_path=registry),
    )

    assert resolve_intake_config(Path("legacy-unit.json"), None, Path("ignored.json")) == (
        "legacy-unit",
        registry,
    )
