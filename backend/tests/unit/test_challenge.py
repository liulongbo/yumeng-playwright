from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from xingtu.challenge import ChallengeHandler, ChallengePolicy
from xingtu.domain import ChallengeState, CollectorError, TaskStatus


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += seconds


class Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    async def is_visible(self):
        return self.page.visible(self.selector)

    async def count(self):
        return 1 if self.page.visible(self.selector) else 0

    async def inner_text(self):
        return self.page.account

    async def get_attribute(self, _name):
        return self.page.account


class ReadOnlyPage:
    def __init__(self, clock, *, challenge, account="expected", login=False):
        self.clock = clock
        self.challenge = challenge
        self.account = account
        self.login = login
        self.locator_reads = 0

    def locator(self, selector):
        self.locator_reads += 1
        return Locator(self, selector)

    def visible(self, selector):
        if selector == "#challenge":
            return self.challenge(self.clock())
        if selector == "#login":
            return self.login
        if selector in {"#ready", "#account"}:
            return not self.challenge(self.clock()) and not self.login
        return False


def session_spec():
    def locator(selector):
        return SimpleNamespace(selector=selector, frame=None, attribute=None)

    return SimpleNamespace(
        error_selectors={
            "ACCOUNT_LOGIN_REQUIRED": locator("#login"),
            "PLATFORM_SECURITY_CHALLENGE": locator("#challenge"),
        },
        protected_ready=locator("#ready"),
        account=locator("#account"),
    )


async def test_stable_window_resets_after_challenge_flicker_without_page_actions():
    clock = Clock()
    page = ReadOnlyPage(
        clock,
        challenge=lambda now: now < 1.0 or 1.5 <= now < 2.0,
    )
    handler = ChallengeHandler(
        None,  # type: ignore[arg-type]
        ChallengePolicy(stable_seconds=1, timeout_seconds=5, poll_seconds=0.25),
        clock=clock,
        sleeper=clock.sleep,
    )

    health = await handler.wait_for_stable_session(page, session_spec(), "expected")

    assert health.status == "VALID"
    assert health.evidence_reason == "CHALLENGE_CLEAR_STABLE_WINDOW"
    assert clock.value >= 3.0
    assert page.locator_reads > 0
    assert not hasattr(page, "goto") and not hasattr(page, "click")


@pytest.mark.parametrize(
    "page_kwargs,code",
    [
        ({"challenge": lambda _now: True}, "SECURITY_CHALLENGE_TIMEOUT"),
        (
            {"challenge": lambda _now: False, "login": True},
            "SECURITY_CHALLENGE_SESSION_INVALID",
        ),
        (
            {"challenge": lambda _now: False, "account": "other"},
            "SECURITY_CHALLENGE_ACCOUNT_MISMATCH",
        ),
    ],
)
async def test_timeout_and_invalid_sessions_are_terminal(page_kwargs, code):
    clock = Clock()
    page = ReadOnlyPage(clock, **page_kwargs)
    handler = ChallengeHandler(
        None,  # type: ignore[arg-type]
        ChallengePolicy(stable_seconds=1, timeout_seconds=1, poll_seconds=0.25),
        clock=clock,
        sleeper=clock.sleep,
    )
    with pytest.raises(CollectorError) as error:
        await handler.wait_for_stable_session(page, session_spec(), "expected")
    assert error.value.code == code


class MemoryRepository:
    def __init__(self, task):
        self.task = task

    @contextmanager
    def edit(self, _root):
        yield self.task, None


def test_creator_and_task_recovery_limits_are_checkpointed():
    candidate = SimpleNamespace(
        state="collecting", ref=SimpleNamespace(platform_creator_id="creator-1")
    )
    checkpoint = SimpleNamespace(
        candidates=[candidate],
        challenge_count=0,
        challenge_recovery_count=0,
        challenge_recoveries_by_creator={},
        challenge_first_detected_at=None,
        challenge_last_detected_at=None,
        challenge_wait_started_at=None,
        challenge_last_recovered_at=None,
        challenge_current_creator=None,
        challenge_type=None,
        challenge_state=None,
    )
    task = SimpleNamespace(
        attempt_id="attempt",
        checkpoint=checkpoint,
        state=TaskStatus.COLLECTING,
        failure_reason=None,
    )
    handler = ChallengeHandler(MemoryRepository(task))  # type: ignore[arg-type]

    first = handler.register("root", "attempt")
    assert first.allowed and task.state == TaskStatus.WAITING_FOR_VERIFICATION
    handler.recovered("root", "attempt", "creator-1")
    assert checkpoint.challenge_recovery_count == 1

    second = handler.register("root", "attempt")
    assert not second.allowed
    assert second.terminal_reason == "SECURITY_CHALLENGE_LIMIT"
    assert checkpoint.challenge_state == ChallengeState.LIMIT_EXCEEDED
    assert checkpoint.challenge_count == 2
