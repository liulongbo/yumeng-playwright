"""Startup reconciliation for a quarantined unit.

The Worker may only clear a quarantine after a local isolation proof.  These tests pin the
fail-closed branches: an active lease/verification/takeover, an unconfirmed reason, a profile
lock, or a live Chromium singleton must all leave the unit untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xingtu.domain import CollectorError
from xingtu.worker import reconcile_quarantined_unit


@dataclass
class FakeConfig:
    unit_id: str = "unit-test"


class FakeRepository:
    def __init__(
        self,
        *,
        state: str = "QUARANTINED",
        reason: str = "EXPIRED_OWNER",
        active: bool = False,
        recover_error: CollectorError | None = None,
    ) -> None:
        self.unit_row = {"state": state, "failure_reason": reason}
        self.active = active
        self.recover_error = recover_error
        self.unit_calls: list[str] = []
        self.recovered: list[tuple[str, str]] = []

    def unit(self, unit_id: str) -> dict[str, Any]:
        self.unit_calls.append(unit_id)
        return self.unit_row

    def has_active_unit_claim(self, unit_id: str) -> bool:
        assert unit_id == "unit-test"
        return self.active

    def recover_stopped_unit(self, unit_id: str, actor: str) -> None:
        self.recovered.append((unit_id, actor))
        if self.recover_error is not None:
            raise self.recover_error


def isolate(monkeypatch: Any) -> list[tuple[str, Path]]:
    calls: list[tuple[str, Path]] = []

    def fake_confirm(config: FakeConfig, private_root: Path) -> None:
        calls.append((config.unit_id, private_root))

    monkeypatch.setattr("xingtu.worker.confirm_local_browser_stopped", fake_confirm)
    return calls


def test_non_quarantined_unit_is_not_touched(monkeypatch: Any) -> None:
    repo = FakeRepository(state="READY")
    calls = isolate(monkeypatch)

    assert reconcile_quarantined_unit(repo, FakeConfig(), Path(".runtime"), "worker-1") is False
    assert calls == []
    assert repo.recovered == []


def test_any_code_generated_quarantine_reason_is_reconciled_after_proof(monkeypatch: Any) -> None:
    """A browser-close failure can carry a session reason, not just EXPIRED_OWNER.

    Quarantined is only produced by expired-owner or unconfirmed-browser paths, so the local
    proof (not a string allowlist) decides recovery.
    """
    repo = FakeRepository(reason="PROTECTED_PAGE_AND_ACCOUNT_VERIFIED")
    calls = isolate(monkeypatch)

    assert reconcile_quarantined_unit(repo, FakeConfig(), Path(".runtime"), "worker-1") is True
    assert calls == [("unit-test", Path(".runtime"))]
    assert repo.recovered == [("unit-test", "collection-worker:worker-1")]


def test_active_lease_verification_or_takeover_blocks_recovery(monkeypatch: Any) -> None:
    repo = FakeRepository(active=True)
    calls = isolate(monkeypatch)

    assert reconcile_quarantined_unit(repo, FakeConfig(), Path(".runtime"), "worker-1") is False
    assert calls == []
    assert repo.recovered == []


def test_failed_isolation_proof_leaves_unit_quarantined(monkeypatch: Any) -> None:
    repo = FakeRepository()

    def busy(config: FakeConfig, private_root: Path) -> None:
        raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_STILL_IN_USE")

    monkeypatch.setattr("xingtu.worker.confirm_local_browser_stopped", busy)

    assert reconcile_quarantined_unit(repo, FakeConfig(), Path(".runtime"), "worker-1") is False
    assert repo.recovered == []


def test_recovery_refusal_is_logged_not_raised(monkeypatch: Any) -> None:
    repo = FakeRepository(
        recover_error=CollectorError("RESOURCE_UNAVAILABLE", "UNIT_NOT_RECOVERABLE")
    )
    isolate(monkeypatch)

    assert reconcile_quarantined_unit(repo, FakeConfig(), Path(".runtime"), "worker-1") is False
    assert repo.recovered == [("unit-test", "collection-worker:worker-1")]


def test_local_isolation_proof_recovers_with_audited_actor(monkeypatch: Any) -> None:
    repo = FakeRepository()
    calls = isolate(monkeypatch)
    root = Path(".runtime/profiles")

    assert reconcile_quarantined_unit(repo, FakeConfig(), root, "worker-1") is True
    assert calls == [("unit-test", root)]
    assert repo.recovered == [("unit-test", "collection-worker:worker-1")]
