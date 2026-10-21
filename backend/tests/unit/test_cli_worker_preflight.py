import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from xingtu.cli import worker_preflight

ROOT = Path(__file__).resolve().parents[3]


def write_unit(tmp_path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "unit_id": "unit-local-test",
        "account_ref": "account-local-test",
        "expected_account_id": "account-id-local-test",
        "line_id": "local-test-line",
        "profile_directory": str(tmp_path / "profile"),
        "registry_path": str(ROOT / "contracts/douyin_xingtu.verified.json"),
        "network_mode": "local_development",
        "browser_executable_path": "/bin/sh",
    }
    payload.update(overrides)
    path = tmp_path / "unit.json"
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    return path


@pytest.mark.asyncio
async def test_worker_preflight_labels_local_unit_as_test_only(tmp_path: Path) -> None:
    report = await worker_preflight(write_unit(tmp_path))

    assert report["unit_id"] == "unit-local-test"
    assert report["network_mode"] == "local_development"
    assert report["line_verification"] == "not_applicable_test_only"
    assert report["test_only"] is True


@pytest.mark.asyncio
async def test_worker_preflight_does_not_accept_proxy_as_local_line(tmp_path: Path) -> None:
    path = write_unit(tmp_path, proxy_server="http://127.0.0.1:1080")

    with pytest.raises(ValidationError, match="local_development unit must not configure proxy"):
        await worker_preflight(path)
