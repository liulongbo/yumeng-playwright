"""Concurrent login must not let a burst reach the expensive password verifier unbounded.

This file records the measured behaviour of ``AuthService.login`` when many requests arrive at
once. It drives the real service with the real ``RedisLoginLimiter`` against a real Redis and
counts how many Argon2 verifications actually execute.

Why a real Redis instead of a fake:
    the defect being pinned is a *cross-round-trip* race. A fake that serialises calls cannot
    reproduce it, and the previous unit coverage only exercised the serial case.

Key isolation:
    ``ScopedRedisLoginLimiter`` overrides the key prefix so no real login bucket can be touched.
    The fixture also asserts Redis is otherwise empty for this prefix and deletes only that prefix.

Cost:
    the production hasher is Argon2id ``time_cost=3, memory_cost=64 MiB, parallelism=4``. Forty
    concurrent verifications at those parameters allocate ~2.5 GiB, which is the very resource
    exhaustion this test measures. The tests therefore use reduced Argon2 parameters so the suite
    stays fast and safe; the gate logic being asserted is independent of the cost parameters.
"""

from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from argon2 import Type as Argon2Type
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from xingtu.domain import CollectorError, uid
from xingtu.product_auth import AuthService, PasswordService, RedisLoginLimiter

PREFIX = "pmreview:concurrency:"
CONCURRENCY = 24
MAX_FAILURES = 5
PASSWORD = "the-correct-password"


def _redis_url() -> str:
    override = os.environ.get("XINGTU_TEST_REDIS_URL")
    if override:
        return override
    env_file = Path(".runtime/m3-app.env")
    if env_file.exists():
        match = re.search(r"XINGTU_REDIS_URL=(\S+)", env_file.read_text())
        if match:
            return match.group(1)
    return "redis://127.0.0.1:56379/0"


class ScopedRedisLoginLimiter(RedisLoginLimiter):
    """Same logic as production, with a disposable key prefix."""

    def _keys(self, ip_address: str, username: str) -> tuple[str, str]:
        ip_key, account_key = super()._keys(ip_address, username)
        return f"{PREFIX}{ip_key}", f"{PREFIX}{account_key}"


class CountingPasswordService(PasswordService):
    """Real Argon2 verification, but cheap, and counted.

    Thread-safe because ``login`` runs on the request's worker thread.
    """

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            type=Argon2Type.ID,
            time_cost=1,
            memory_cost=8,
            parallelism=1,
            hash_len=16,
            salt_len=8,
        )
        self._lock = threading.Lock()
        self.verify_calls = 0

    def verify(self, encoded: str, password: str) -> bool:
        with self._lock:
            self.verify_calls += 1
        return super().verify(encoded, password)

    def reset_counter(self) -> None:
        with self._lock:
            self.verify_calls = 0


class CountingStore:
    """Minimal AuthStore.

    ``find_user_for_login`` is the first statement after ``limiter.check()`` and immediately before
    the password verification, so a barrier here holds every request at exactly the point where the
    read-then-act race is decided. That makes the interleaving deterministic instead of flaky.
    """

    def __init__(self, password_hash: str, barrier: threading.Barrier | None = None) -> None:
        self.user = {
            "user_id": uid(),
            "username": "victim",
            "display_name": "Victim",
            "password_hash": password_hash,
            "active": True,
        }
        self.barrier = barrier

    def find_user_for_login(self, username: str) -> dict[str, object] | None:
        if self.barrier is not None:
            self.barrier.wait()
        return self.user if username == self.user["username"] else None

    def create_session(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        raise CollectorError("RESOURCE_UNAVAILABLE", "SESSION_WRITE_NOT_UNDER_TEST")

    def resolve_session(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def revoke_session(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None


@pytest.fixture
def redis_client():
    client = Redis.from_url(_redis_url(), decode_responses=True)
    try:
        client.ping()
    except (RedisConnectionError, OSError):  # pragma: no cover - environment dependent
        pytest.skip("Redis unavailable for the login-concurrency test")
    stale = client.keys(f"{PREFIX}*")
    assert not stale, "the disposable prefix must start empty"
    try:
        yield client
    finally:
        for key in client.keys(f"{PREFIX}*"):
            client.delete(key)


def build_auth(
    redis_client, *, barrier: threading.Barrier | None = None
) -> tuple[tuple[AuthService, CountingPasswordService], CountingStore]:
    passwords = CountingPasswordService()
    store = CountingStore(passwords.hash(PASSWORD), barrier)
    limiter = ScopedRedisLoginLimiter(
        redis_client, b"k" * 32, max_failures=MAX_FAILURES, window_seconds=900
    )
    auth = AuthService(store, limiter, passwords=passwords)
    return (auth, passwords), store


def burst(auth: AuthService, password: str) -> list[str]:
    """Fire CONCURRENCY simultaneous logins and collect their outcome codes."""

    def attempt(_: int) -> str:
        try:
            auth.login("victim", password, "203.0.113.9")
            return "ok"
        except CollectorError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        return list(pool.map(attempt, range(CONCURRENCY)))


def test_concurrent_wrong_passwords_all_reach_the_password_verifier(redis_client):
    """DOCUMENTED DEFECT: the failure bucket does not throttle a concurrent burst.

    ``login`` calls ``limiter.check()``, then Argon2, then ``limiter.failure()``. Every request in
    a simultaneous burst observes an empty bucket before any of them records a failure, so the
    whole burst reaches Argon2. With production parameters that is CONCURRENCY x 64 MiB of ARgon2
    work and it is capped only by the request thread pool (40 by default), not by ``max_failures``.

    Asserting the current behaviour keeps the exposure visible. When the recommended fix lands
    (an atomic attempt gate evaluated before the verifier, see
    docs/testing/regression-f04-m3-2026-10-12.md), this expectation must be tightened to
    ``<= max_attempts`` rather than deleted.
    """
    barrier = threading.Barrier(CONCURRENCY)
    (auth, passwords), _store = build_auth(redis_client, barrier=barrier)

    outcomes = burst(auth, "wrong-password")

    assert outcomes.count("ok") == 0
    assert outcomes.count("INVALID_FORM") == CONCURRENCY
    # Nothing throttled the burst before the verifier: every request paid the Argon2 cost.
    assert outcomes.count("PLATFORM_RATE_LIMITED") == 0
    assert passwords.verify_calls == CONCURRENCY


def test_concurrent_correct_passwords_are_not_counted_as_failures(redis_client):
    """Correct credentials must never consume the failure budget, even under a burst.

    The failure bucket is only touched after the password comparison fails, so a burst of valid
    logins has to leave the limiter untouched. This is the invariant a naive
    "increment before verifying" gate would break.
    """
    barrier = threading.Barrier(CONCURRENCY)
    (auth, passwords), _store = build_auth(redis_client, barrier=barrier)

    outcomes = burst(auth, PASSWORD)

    assert outcomes.count("RESOURCE_UNAVAILABLE") == CONCURRENCY
    assert passwords.verify_calls == CONCURRENCY

    for key in redis_client.keys(f"{PREFIX}*"):
        assert redis_client.get(key) in (None, "0"), "a successful login must not record a failure"


def test_serial_failures_still_block_at_the_documented_threshold(redis_client):
    """The existing serial contract for max_failures must not regress."""
    (auth, _passwords), _store = build_auth(redis_client)

    for _ in range(MAX_FAILURES):
        with pytest.raises(CollectorError) as first:
            auth.login("victim", "wrong-password", "203.0.113.9")
        assert first.value.code == "INVALID_FORM"

    with pytest.raises(CollectorError) as blocked:
        auth.login("victim", "wrong-password", "203.0.113.9")
    assert blocked.value.code == "PLATFORM_RATE_LIMITED"
