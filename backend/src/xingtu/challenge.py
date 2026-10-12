from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from playwright.async_api import Error as BrowserError
from pydantic import BaseModel, ConfigDict, Field

from .domain import (
    ChallengeState,
    ChallengeType,
    CollectorError,
    SessionHealth,
    SessionHealthStatus,
    TaskStatus,
    utcnow,
)
from .repository import Repository


class ChallengePolicy(BaseModel):
    """Product-owned limits; deliberately not exposed as end-user controls."""

    model_config = ConfigDict(extra="forbid")

    stable_seconds: float = Field(default=5.0, ge=0)
    timeout_seconds: float = Field(default=900.0, gt=0)
    recovery_cooldown_seconds: float = Field(default=60.0, ge=0)
    creator_interval_seconds: float = Field(default=15.0, ge=0)
    max_task_recoveries: int = Field(default=2, ge=0)
    max_creator_recoveries: int = Field(default=1, ge=0)
    poll_seconds: float = Field(default=0.25, gt=0)


@dataclass(frozen=True)
class ChallengeAttempt:
    creator_id: str | None
    allowed: bool
    terminal_reason: str | None = None


class ChallengeHandler:
    """Detect, checkpoint and observe platform verification without solving or bypassing it.

    While this object waits it performs DOM reads only. It never clicks, navigates, reloads,
    fetches a cover, changes a user agent or interacts with the verification widget.
    """

    def __init__(
        self,
        repository: Repository,
        policy: ChallengePolicy | None = None,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.repository = repository
        self.policy = policy or ChallengePolicy()
        self.clock = clock or time.monotonic
        self.sleep = sleeper or asyncio.sleep

    @staticmethod
    def current_creator(task: Any) -> str | None:
        candidate = next(
            (item for item in task.checkpoint.candidates if item.state == "collecting"), None
        )
        return candidate.ref.platform_creator_id if candidate else None

    def register(self, root: str, attempt_id: str) -> ChallengeAttempt:
        """Persist one detection and atomically enforce task/creator recovery limits."""

        now = utcnow()
        with self.repository.edit(root) as (task, _):
            if task.attempt_id != attempt_id:
                raise CollectorError("TASK_CANCELLED", "STALE_CHALLENGE_ATTEMPT")
            creator = self.current_creator(task)
            cp = task.checkpoint
            cp.challenge_count += 1
            cp.challenge_first_detected_at = cp.challenge_first_detected_at or now
            cp.challenge_last_detected_at = now
            cp.challenge_wait_started_at = now
            cp.challenge_current_creator = creator
            cp.challenge_type = ChallengeType.SLIDER_OR_INTERACTIVE
            creator_recoveries = (
                cp.challenge_recoveries_by_creator.get(creator, 0) if creator else 0
            )
            limited = (
                cp.challenge_recovery_count >= self.policy.max_task_recoveries
                or creator_recoveries >= self.policy.max_creator_recoveries
            )
            if limited:
                cp.challenge_state = ChallengeState.LIMIT_EXCEEDED
                task.failure_reason = "SECURITY_CHALLENGE_LIMIT"
                return ChallengeAttempt(creator, False, "SECURITY_CHALLENGE_LIMIT")
            cp.challenge_state = ChallengeState.HANDLING
            task.state = TaskStatus.WAITING_FOR_VERIFICATION
            task.failure_reason = "PLATFORM_SECURITY_CHALLENGE"
            return ChallengeAttempt(creator, True)

    def recovered(self, root: str, attempt_id: str, creator_id: str | None) -> None:
        now = utcnow()
        with self.repository.edit(root) as (task, _):
            if task.attempt_id != attempt_id:
                raise CollectorError("TASK_CANCELLED", "STALE_CHALLENGE_ATTEMPT")
            cp = task.checkpoint
            cp.challenge_recovery_count += 1
            if creator_id:
                cp.challenge_recoveries_by_creator[creator_id] = (
                    cp.challenge_recoveries_by_creator.get(creator_id, 0) + 1
                )
            cp.challenge_last_recovered_at = now
            cp.challenge_wait_started_at = None
            cp.challenge_state = ChallengeState.VERIFIED
            task.state = TaskStatus.QUEUED
            task.failure_reason = None

    def failed(self, root: str, attempt_id: str, reason: str) -> None:
        state = (
            ChallengeState.TIMEOUT
            if reason == "SECURITY_CHALLENGE_TIMEOUT"
            else ChallengeState.FAILED
        )
        with self.repository.edit(root) as (task, _):
            if task.attempt_id != attempt_id:
                raise CollectorError("TASK_CANCELLED", "STALE_CHALLENGE_ATTEMPT")
            task.checkpoint.challenge_state = state
            if reason == "SECURITY_CHALLENGE_SESSION_INVALID":
                task.checkpoint.challenge_type = ChallengeType.LOGIN_REQUIRED
            elif reason == "SECURITY_CHALLENGE_ACCOUNT_MISMATCH":
                task.checkpoint.challenge_type = ChallengeType.ACCOUNT_MISMATCH
            elif reason == "SECURITY_CHALLENGE_UNKNOWN":
                task.checkpoint.challenge_type = ChallengeType.UNKNOWN_SECURITY_CHALLENGE
            task.checkpoint.challenge_wait_started_at = None
            task.failure_reason = reason

    @staticmethod
    def _locator(page: Any, locator: Any) -> Any:
        return (
            page.frame_locator(locator.frame).locator(locator.selector)
            if locator.frame
            else page.locator(locator.selector)
        )

    async def wait_for_stable_session(
        self,
        page: Any,
        session_spec: Any,
        expected_account_id: str,
        timeout_seconds: float | None = None,
    ) -> SessionHealth:
        """Wait for a continuously valid registered surface, using read-only observations."""

        deadline = self.clock() + (
            self.policy.timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        stable_since: float | None = None
        while True:
            now = self.clock()
            if now >= deadline:
                raise CollectorError("SECURITY_CHALLENGE_TIMEOUT", "VERIFICATION_WAIT_EXPIRED")
            try:
                visible_errors = {
                    code
                    for code, locator in session_spec.error_selectors.items()
                    if await self._locator(page, locator).is_visible()
                }
                if "PLATFORM_SECURITY_CHALLENGE" in visible_errors:
                    stable_since = None
                elif "ACCOUNT_LOGIN_REQUIRED" in visible_errors:
                    raise CollectorError(
                        "SECURITY_CHALLENGE_SESSION_INVALID", "REGISTERED_LOGIN_PAGE"
                    )
                elif visible_errors:
                    raise CollectorError("SECURITY_CHALLENGE_UNKNOWN", sorted(visible_errors)[0])
                elif await self._locator(page, session_spec.protected_ready).is_visible():
                    account_locator = self._locator(page, session_spec.account)
                    account = ""
                    if await account_locator.count() == 1 and await account_locator.is_visible():
                        raw = (
                            await account_locator.get_attribute(session_spec.account.attribute)
                            if session_spec.account.attribute
                            else await account_locator.inner_text()
                        )
                        account = (raw or "").strip()
                    if account and account != expected_account_id:
                        raise CollectorError("SECURITY_CHALLENGE_ACCOUNT_MISMATCH", "WRONG_ACCOUNT")
                    if account == expected_account_id:
                        stable_since = stable_since if stable_since is not None else now
                        if now - stable_since >= self.policy.stable_seconds:
                            return SessionHealth(
                                status=SessionHealthStatus.VALID,
                                expected_account_id=expected_account_id,
                                observed_account_id=account,
                                protected_page_verified=True,
                                evidence_reason="CHALLENGE_CLEAR_STABLE_WINDOW",
                            )
                    else:
                        stable_since = None
                else:
                    stable_since = None
            except CollectorError:
                raise
            except BrowserError:
                stable_since = None
            remaining = max(0.0, deadline - self.clock())
            await self.sleep(min(self.policy.poll_seconds, remaining))

    async def cooldown(self) -> None:
        if self.policy.recovery_cooldown_seconds:
            await self.sleep(self.policy.recovery_cooldown_seconds)

    def waiting_seconds(self, task: Any) -> int:
        started = task.checkpoint.challenge_wait_started_at
        if not started:
            return 0
        return max(0, int((utcnow() - started).total_seconds()))

    def remaining_timeout(self, task: Any) -> float:
        """Keep one challenge wait bounded even when an Activity/Worker restarts."""

        return max(0.0, self.policy.timeout_seconds - self.waiting_seconds(task))

    @property
    def maintenance_ttl(self) -> timedelta:
        return timedelta(seconds=self.policy.timeout_seconds)
