from datetime import timedelta

import pytest
from redis.exceptions import ConnectionError
from xingtu.domain import CollectorError, uid, utcnow
from xingtu.product_auth import (
    GENERIC_LOGIN_ERROR,
    AuthService,
    MemoryLoginLimiter,
    PasswordService,
    RedisLoginLimiter,
    hash_secret,
    normalize_username,
)


class MemoryAuthStore:
    def __init__(self, password_hash):
        self.user = {
            "user_id": uid(),
            "username": "media",
            "display_name": "媒介 A",
            "password_hash": password_hash,
            "active": True,
        }
        self.sessions = {}

    def find_user_for_login(self, username):
        return self.user if username == self.user["username"] else None

    def create_session(self, user_id, token_hash, csrf_token, idle_expires_at, absolute_expires_at):
        session_id = uid()
        self.sessions[token_hash] = {
            "session_id": session_id,
            "user_id": user_id,
            "username": self.user["username"],
            "display_name": self.user["display_name"],
            "csrf_token": csrf_token,
            "idle_expires_at": idle_expires_at,
            "absolute_expires_at": absolute_expires_at,
            "revoked": False,
        }
        return session_id

    def resolve_session(self, token_hash, idle_extension: timedelta):
        row = self.sessions.get(token_hash)
        if (
            not row
            or row["revoked"]
            or row["idle_expires_at"] <= utcnow()
            or row["absolute_expires_at"] <= utcnow()
            or not self.user["active"]
        ):
            return None
        row["idle_expires_at"] = min(row["absolute_expires_at"], utcnow() + idle_extension)
        return row

    def revoke_session(self, token_hash, actor_user_id):
        del actor_user_id
        if token_hash in self.sessions:
            self.sessions[token_hash]["revoked"] = True


def auth_fixture(max_failures=5):
    passwords = PasswordService()
    store = MemoryAuthStore(passwords.hash("a-secure-password"))
    return AuthService(
        store,
        MemoryLoginLimiter(max_failures=max_failures),
        passwords=passwords,
    ), store


def test_argon2id_password_and_server_session_lifecycle():
    auth, store = auth_fixture()
    session = auth.login("Media", "a-secure-password", "127.0.0.1")
    assert normalize_username("  MEDIA ") == "media"
    assert store.user["password_hash"].startswith("$argon2id$")
    current = auth.authenticate(session.token)
    assert current.user_id == store.user["user_id"]
    assert current.csrf_token == session.user.csrf_token
    auth.require_csrf(current, session.user.csrf_token)
    with pytest.raises(CollectorError, match="CSRF_CHECK_FAILED"):
        auth.require_csrf(current, "wrong")
    auth.logout(session.token, current.user_id)
    with pytest.raises(CollectorError, match="PRODUCT_SESSION_INVALID"):
        auth.authenticate(session.token)


def test_login_error_does_not_enumerate_user_or_status():
    auth, store = auth_fixture()
    for username in ("missing", "media"):
        if username == "media":
            store.user["active"] = False
        with pytest.raises(CollectorError) as error:
            auth.login(username, "wrong-password", "127.0.0.1")
        assert error.value.reason == GENERIC_LOGIN_ERROR


def test_login_limiter_blocks_after_bounded_failures():
    auth, _ = auth_fixture(max_failures=2)
    for _ in range(2):
        with pytest.raises(CollectorError, match=GENERIC_LOGIN_ERROR):
            auth.login("media", "wrong-password", "127.0.0.1")
    with pytest.raises(CollectorError, match="LOGIN_RATE_LIMITED"):
        auth.login("media", "a-secure-password", "127.0.0.1")


def test_session_database_key_is_a_hash_not_cookie_value():
    auth, store = auth_fixture()
    session = auth.login("media", "a-secure-password", "127.0.0.1")
    assert session.token not in store.sessions
    assert hash_secret(session.token) in store.sessions


def test_redis_limiter_fails_closed_when_redis_is_unavailable():
    class BrokenRedis:
        def mget(self, keys):
            del keys
            raise ConnectionError("offline")

    limiter = RedisLoginLimiter(BrokenRedis(), b"x" * 32)
    with pytest.raises(CollectorError, match="LOGIN_LIMITER_UNAVAILABLE"):
        limiter.check("127.0.0.1", "media")
