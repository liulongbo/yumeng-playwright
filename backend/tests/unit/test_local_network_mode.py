"""Local-development network mode: explicit, fail-closed and never a production line proof.

All data here is synthetic; no page is opened and no platform host is contacted.
"""

import asyncio
import json

import pytest
from pydantic import ValidationError
from xingtu.domain import CollectorError, NetworkMode
from xingtu.evidence import EvidenceSummary
from xingtu.runtime import (
    BrowserRuntime,
    UnitConfig,
    close_browser_context,
    confirm_local_browser_stopped,
    ensure_line,
    load_unit,
    local_network_attestation,
)

PRODUCTION = {
    "unit_id": "unit-prod",
    "account_ref": "acct",
    "expected_account_id": "acct-id",
    "line_id": "line-1",
    "profile_directory": "/tmp/profile",
    "registry_path": "/tmp/registry.json",
    "proxy_server": "http://127.0.0.1:8899",
    "network_evidence_path": "/tmp/proof.json",
    "network_probe_command": ["probe"],
}

LOCAL = {
    "unit_id": "unit-local",
    "account_ref": "acct",
    "expected_account_id": "acct-id",
    "line_id": "local-dev",
    "profile_directory": "/tmp/profile",
    "registry_path": "/tmp/registry.json",
    "network_mode": "local_development",
    "browser_executable_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "research_allowed_hosts": ["www.xingtu.cn"],
}


def test_production_line_still_requires_proxy_proof_and_probe():
    UnitConfig.model_validate(PRODUCTION)
    for missing in ("proxy_server", "network_evidence_path", "network_probe_command"):
        payload = {k: v for k, v in PRODUCTION.items() if k != missing}
        with pytest.raises(ValidationError):
            UnitConfig.model_validate(payload)


def test_local_development_rejects_proxy_and_production_proof():
    for extra in (
        {"proxy_server": "http://127.0.0.1:8899"},
        {"network_evidence_path": "/tmp/proof.json"},
        {"network_probe_command": ["probe"]},
    ):
        with pytest.raises(ValidationError):
            UnitConfig.model_validate({**LOCAL, **extra})


def test_local_development_browser_binding_is_exclusive():
    with pytest.raises(ValidationError):
        UnitConfig.model_validate({**LOCAL, "browser_channel": "chrome"})


def test_local_config_is_explicit_and_not_a_network_proof():
    config = UnitConfig.model_validate(LOCAL)
    assert config.network_mode is NetworkMode.LOCAL_DEVELOPMENT
    assert config.is_local_development
    attestation = local_network_attestation(config)
    assert attestation["network_mode"] == "local_development"
    assert attestation["egress"] == "local_machine"
    # A local attestation deliberately carries none of the production line proof fields.
    proof_fields = {"dns_bound", "disconnect_blocks_direct", "worker_egress_enforced"}
    assert not proof_fields & set(attestation)


async def test_ensure_line_local_needs_no_proof_but_rejects_a_proxy():
    config = UnitConfig.model_validate(LOCAL)
    await ensure_line(config)
    smuggled = config.model_copy(update={"proxy_server": "http://127.0.0.1:8899"})
    with pytest.raises(CollectorError, match="LOCAL_MODE_MUST_NOT_USE_PROXY"):
        await ensure_line(smuggled)


async def test_ensure_line_production_is_unavailable_without_a_valid_proof(tmp_path):
    config = UnitConfig.model_validate(
        {**PRODUCTION, "network_evidence_path": tmp_path / "missing.json"}
    )
    with pytest.raises(CollectorError) as exc:
        await ensure_line(config)
    assert exc.value.reason == "LINE_VERIFICATION_UNAVAILABLE"


async def test_local_profile_must_stay_inside_project_private_root(tmp_path):
    config = UnitConfig.model_validate(
        {**LOCAL, "profile_directory": str(tmp_path / "outside-profile")}
    )
    runtime = BrowserRuntime(config, tmp_path / "private")
    with pytest.raises(CollectorError, match="PROFILE_OUTSIDE_PROJECT_PRIVATE_ROOT"):
        async with runtime.open():
            pass


def test_macos_system_keychain_ignores_only_playwright_mock_keychain(tmp_path, monkeypatch):
    executable = tmp_path / "Google Chrome"
    executable.touch(mode=0o700)
    config = UnitConfig.model_validate(
        {
            **LOCAL,
            "browser_executable_path": str(executable),
            "macos_system_keychain": True,
        }
    )
    monkeypatch.setattr("xingtu.runtime.sys.platform", "darwin")
    runtime = BrowserRuntime(config, tmp_path)

    assert runtime._launch_options()["ignore_default_args"] == ["--use-mock-keychain"]
    assert (
        runtime.environment_hash
        != BrowserRuntime(
            config.model_copy(update={"macos_system_keychain": False}), tmp_path
        ).environment_hash
    )


def test_system_keychain_fails_closed_outside_macos_executable(tmp_path, monkeypatch):
    config = UnitConfig.model_validate({**LOCAL, "macos_system_keychain": True})
    monkeypatch.setattr("xingtu.runtime.sys.platform", "linux")

    with pytest.raises(CollectorError, match="SYSTEM_KEYCHAIN_REQUIRES_MACOS_EXECUTABLE"):
        BrowserRuntime(config, tmp_path)._launch_options()


async def test_browser_close_is_bounded_and_never_certifies_a_hung_context():
    class HangingContext:
        async def close(self):
            await asyncio.Event().wait()

    with pytest.raises(CollectorError) as exc:
        await close_browser_context(HangingContext(), timeout_seconds=0.01)  # type: ignore[arg-type]
    assert exc.value.reason == "BROWSER_CLOSE_TIMEOUT"


def test_browser_recovery_uses_project_lock_and_singleton_pid_without_ps(tmp_path, monkeypatch):
    private_root = tmp_path / "profiles"
    profile = private_root / "unit"
    profile.mkdir(parents=True)
    config = UnitConfig.model_validate({**LOCAL, "profile_directory": str(profile)})
    singleton = profile / "SingletonLock"
    singleton.symlink_to("synthetic-host-424242")

    def stale(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr("xingtu.runtime.os.kill", stale)
    confirm_local_browser_stopped(config, private_root)

    monkeypatch.setattr("xingtu.runtime.os.kill", lambda _pid, _signal: None)
    with pytest.raises(CollectorError, match="OLD_PROCESS_STILL_VISIBLE"):
        confirm_local_browser_stopped(config, private_root)


def test_research_next_page_request_is_fixed_and_does_not_mutate_page_one():
    from xingtu.research import identity_digest, next_search_payload

    original = {"page_param": {"page": 1, "limit": 20}, "search_param": {"keyword": "x"}}
    page_two = next_search_payload(original)
    assert page_two["page_param"] == {"page": 2, "limit": 20}
    assert original["page_param"]["page"] == 1
    with pytest.raises(CollectorError, match="SEARCH_PAGE_ONE_REQUIRED"):
        next_search_payload(page_two)
    first = identity_digest({"authors": [{"star_id": "one"}, {"star_id": "two"}]})
    second = identity_digest({"authors": [{"star_id": "three"}, {"star_id": "four"}]})
    assert first and second and first["count"] == second["count"] == 2
    assert first["sha256"] != second["sha256"]


def test_unit_config_file_permissions_are_enforced(tmp_path):
    path = tmp_path / "unit.json"
    path.write_text(json.dumps(LOCAL))
    path.chmod(0o644)
    with pytest.raises(CollectorError, match="PRIVATE_FILE_PERMISSIONS_REQUIRED"):
        load_unit(path)
    path.chmod(0o600)
    assert load_unit(path).network_mode is NetworkMode.LOCAL_DEVELOPMENT


def test_evidence_summary_labels_the_network_mode():
    summary = EvidenceSummary(
        root_task_id="r",
        task_id="t",
        attempt_id="a",
        execution_unit_id="u",
        operation_id="o",
        contract_version="c",
        source_contract="c",
        kind="summary",
        network_mode=NetworkMode.LOCAL_DEVELOPMENT,
    )
    assert json.loads(summary.body())["network_mode"] == "local_development"
    assert (
        EvidenceSummary(
            root_task_id="r",
            task_id="t",
            attempt_id="a",
            execution_unit_id="u",
            operation_id="o",
            contract_version="c",
            source_contract="c",
            kind="summary",
        ).network_mode
        is NetworkMode.PRODUCTION_LINE
    )


async def test_research_is_refused_outside_local_development(tmp_path):
    from xingtu.research import run_research

    production = UnitConfig.model_validate(PRODUCTION)
    with pytest.raises(CollectorError, match="RESEARCH_REQUIRES_LOCAL_DEVELOPMENT_MODE"):
        await run_research(
            production,
            tmp_path,
            start_url="https://www.xingtu.cn/",
            out_dir=tmp_path / "capture",
            steps=[],
            login_wait_seconds=0,
            screenshots=False,
        )


async def test_research_refuses_hosts_outside_the_declared_allowlist(tmp_path):
    from xingtu.research import run_research

    local = UnitConfig.model_validate(LOCAL)
    with pytest.raises(CollectorError, match="RESEARCH_HOST_NOT_ALLOWED"):
        await run_research(
            local,
            tmp_path,
            start_url="https://example.invalid/",
            out_dir=tmp_path / "capture",
            steps=[],
            login_wait_seconds=0,
            screenshots=False,
        )
