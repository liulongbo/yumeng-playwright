"""Pure checks of the JUXING-MAIN-01 main-station switch tooling (no database, no platform)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts import juxing_main_switch as switch  # noqa: E402


def _write_private(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    path.chmod(0o600)


def _config(root: Path, *, juxing: dict | None = None, expected_account: str = "ID: 1") -> dict:
    config = {
        "unit_id": "unit-x",
        "account_ref": "xingtu-account",
        "expected_account_id": expected_account,
        "line_id": "local-x",
        "profile_directory": str(root / "profiles" / "unit-x"),
        "registry_path": str(ROOT / "contracts/douyin_xingtu.verified.json"),
        "network_mode": "local_development",
        "browser_executable_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "research_allowed_hosts": ["www.xingtu.cn"],
    }
    if juxing is not None:
        config["platform_bindings"] = [juxing]
    return config


def _juxing_binding(root: Path) -> dict:
    return {
        "platform": "kuaishou_juxing",
        "account_ref": "juxing-account-02",
        "expected_account_id": "60821564",
        "profile_directory": str(root / "profiles" / "unit-x-juxing"),
        "registry_path": str(ROOT / "contracts/kuaishou_juxing.verified.json"),
        "enabled": True,
    }


def _prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime_root = tmp_path / ".runtime"
    live_profile = runtime_root / "profiles" / "unit-x"
    juxing_profile = runtime_root / "profiles" / "unit-x-juxing"
    live_profile.mkdir(parents=True, mode=0o700)
    juxing_profile.mkdir(mode=0o700)
    live_profile.chmod(0o700)
    juxing_profile.chmod(0o700)
    snapshot = runtime_root / "storage-state" / "unit-x.kuaishou_juxing.json"
    _write_private(
        snapshot,
        {
            "schema_version": "session_snapshot.v1",
            "unit_id": "unit-x",
            "captured_at": "2026-10-28T08:03:59+00:00",
            "storage_state": {
                "cookies": [{"domain": ".kuaishou.com", "name": "synthetic"}],
                "origins": [],
            },
        },
    )
    live_path = tmp_path / "live.json"
    _write_private(live_path, _config(runtime_root))
    return runtime_root, live_path, snapshot


def test_candidate_that_only_adds_the_juxing_binding_is_accepted(tmp_path):
    runtime_root, live_path, _ = _prepare(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    _write_private(candidate_path, _config(runtime_root, juxing=_juxing_binding(runtime_root)))

    checks = switch.config_checks(
        live_path,
        candidate_path,
        runtime_root,
        "unit-x",
        "60821564",
    )
    failed = [check for check in checks if check.required and not check.ok]
    assert failed == []
    names = {check.name for check in checks}
    assert {"CANDIDATE_ONLY_ADDS_BINDING", "JUXING_SNAPSHOT_PRESENT"} <= names


def test_candidate_changing_a_star_chart_field_is_rejected(tmp_path):
    runtime_root, live_path, _ = _prepare(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    _write_private(
        candidate_path,
        _config(runtime_root, juxing=_juxing_binding(runtime_root), expected_account="ID: 2"),
    )

    checks = switch.config_checks(live_path, candidate_path, runtime_root, "unit-x", "60821564")
    only_adds = next(check for check in checks if check.name == "CANDIDATE_ONLY_ADDS_BINDING")
    assert only_adds.ok is False


def test_candidate_without_the_juxing_binding_is_rejected(tmp_path):
    runtime_root, live_path, _ = _prepare(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    _write_private(candidate_path, _config(runtime_root))

    checks = switch.config_checks(live_path, candidate_path, runtime_root, "unit-x", "60821564")
    one_binding = next(
        check for check in checks if check.name == "CANDIDATE_HAS_ONE_JUXING_BINDING"
    )
    assert one_binding.ok is False


def test_env_checks_require_the_three_additions_and_the_current_limit():
    good = {
        "XINGTU_ENABLE_KUAISHOU_JUXING": "1",
        "XINGTU_JUXING_REGISTRY_PATH": str(ROOT / "contracts/kuaishou_juxing.verified.json"),
        "XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT": "30",
    }
    checks = switch.env_checks({}, good, ROOT / ".runtime")
    assert all(check.ok for check in checks if check.required)

    checks = switch.env_checks(
        {},
        {
            "XINGTU_ENABLE_KUAISHOU_JUXING": "0",
            "XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT": "30",
            "XINGTU_UNRELATED": "1",
        },
        ROOT / ".runtime",
    )
    failed = {check.name for check in checks if not check.ok}
    assert {"ENV_ADDITIONS_SCOPE", "EFFECTIVE_JUXING_FLAG"} <= failed
    assert "JUXING_MAX_TARGET_IS_30" not in failed
