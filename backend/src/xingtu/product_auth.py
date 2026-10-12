from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type
from redis import Redis
from redis.exceptions import RedisError

from .domain import CollectorError, utcnow
from .product_models import AuthenticatedUser

GENERIC_LOGIN_ERROR = "用户名或密码错误"


def normalize_username(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    if not normalized or len(normalized) > 128 or any(char.isspace() for char in normalized):
        raise CollectorError("INVALID_FORM", GENERIC_LOGIN_ERROR)
    return normalized


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher(type=Type.ID)

    def hash(self, password: str) -> str:
        if len(password) < 12:
            raise CollectorError("INVALID_FORM", "PASSWORD_TOO_SHORT")
        return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded, password)
        except (VerifyMismatchError, InvalidHashError):
            return False


class LoginLimiter(Protocol):
    def check(self, ip_address: str, username: str) -> None: ...

    def failure(self, ip_address: str, username: str) -> None: ...

    def success(self, ip_address: str, username: str) -> None: ...


class RedisLoginLimiter:
    """A deliberately small fixed-window limiter with IP and account-HMAC buckets."""

    def __init__(
        self,
        client: Redis,
        hmac_key: bytes,
        *,
        max_failures: int = 5,
        window_seconds: int = 900,
    ) -> None:
        if len(hmac_key) < 32:
            raise ValueError("login limiter HMAC key must contain at least 256 bits")
        self.client = client
        self.hmac_key = hmac_key
        self.max_failures = max_failures
        self.window_seconds = window_seconds

    def _keys(self, ip_address: str, username: str) -> tuple[str, str]:
        account = hmac.new(self.hmac_key, username.encode(), hashlib.sha256).hexdigest()
        ip_digest = hmac.new(self.hmac_key, ip_address.encode(), hashlib.sha256).hexdigest()
        return f"xingtu:login:ip:{ip_digest}", f"xingtu:login:account:{account}"

    def check(self, ip_address: str, username: str) -> None:
        try:
            counts = cast(list[Any], self.client.mget(self._keys(ip_address, username)))
        except RedisError as exc:
            raise CollectorError("RESOURCE_UNAVAILABLE", "LOGIN_LIMITER_UNAVAILABLE") from exc
        if any(int(value or 0) >= self.max_failures for value in counts):
            raise CollectorError("PLATFORM_RATE_LIMITED", "LOGIN_RATE_LIMITED")

    def failure(self, ip_address: str, username: str) -> None:
        try:
            with self.client.pipeline(transaction=True) as pipeline:
                for key in self._keys(ip_address, username):
                    pipeline.incr(key)
                    pipeline.expire(key, self.window_seconds)
                pipeline.execute()
        except RedisError as exc:
            raise CollectorError("RESOURCE_UNAVAILABLE", "LOGIN_LIMITER_UNAVAILABLE") from exc

    def success(self, ip_address: str, username: str) -> None:
        try:
            self.client.delete(*self._keys(ip_address, username))
        except RedisError as exc:
            raise CollectorError("RESOURCE_UNAVAILABLE", "LOGIN_LIMITER_UNAVAILABLE") from exc


class MemoryLoginLimiter:
    """Deterministic test adapter; production wiring must use RedisLoginLimiter."""

    def __init__(self, max_failures: int = 5) -> None:
        self.max_failures = max_failures
        self.failures: dict[tuple[str, str], int] = {}

    def check(self, ip_address: str, username: str) -> None:
        if self.failures.get((ip_address, username), 0) >= self.max_failures:
            raise CollectorError("PLATFORM_RATE_LIMITED", "LOGIN_RATE_LIMITED")

    def failure(self, ip_address: str, username: str) -> None:
        key = (ip_address, username)
        self.failures[key] = self.failures.get(key, 0) + 1

    def success(self, ip_address: str, username: str) -> None:
        self.failures.pop((ip_address, username), None)


class AuthStore(Protocol):
    def find_user_for_login(self, username: str) -> dict[str, object] | None: ...

    def create_session(
        self,
        user_id: str,
        token_hash: str,
        csrf_token: str,
        idle_expires_at: object,
        absolute_expires_at: object,
    ) -> str: ...

    def resolve_session(
        self, token_hash: str, idle_extension: timedelta
    ) -> dict[str, object] | None: ...

    def revoke_session(self, token_hash: str, actor_user_id: str | None) -> None: ...


@dataclass(frozen=True)
class NewSession:
    user: AuthenticatedUser
    token: str


class AuthService:
    def __init__(
        self,
        store: AuthStore,
        limiter: LoginLimiter,
        *,
        idle_timeout: timedelta = timedelta(hours=8),
        absolute_timeout: timedelta = timedelta(days=7),
        passwords: PasswordService | None = None,
    ) -> None:
        self.store = store
        self.limiter = limiter
        self.idle_timeout = idle_timeout
        self.absolute_timeout = absolute_timeout
        self.passwords = passwords or PasswordService()
        # Unknown and disabled users must still pay the same password-verification cost.
        # The value is process-local and never represents a login credential.
        self._dummy_hash = self.passwords.hash(secrets.token_urlsafe(32))

    def login(self, username: str, password: str, ip_address: str) -> NewSession:
        try:
            normalized = normalize_username(username)
        except CollectorError:
            normalized = "invalid-user"
        self.limiter.check(ip_address, normalized)
        row = self.store.find_user_for_login(normalized)
        stored_hash = row.get("password_hash") if row is not None else None
        encoded = stored_hash if isinstance(stored_hash, str) else self._dummy_hash
        password_matches = self.passwords.verify(encoded, password)
        if row is None or not row.get("active") or not password_matches:
            self.limiter.failure(ip_address, normalized)
            raise CollectorError("INVALID_FORM", GENERIC_LOGIN_ERROR)
        self.limiter.success(ip_address, normalized)
        now = utcnow()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        user_id = str(row["user_id"])
        session_id = self.store.create_session(
            user_id,
            hash_secret(token),
            csrf,
            now + self.idle_timeout,
            now + self.absolute_timeout,
        )
        return NewSession(
            user=AuthenticatedUser(
                user_id=user_id,
                username=str(row["username"]),
                display_name=str(row["display_name"]),
                session_id=session_id,
                csrf_token=csrf,
            ),
            token=token,
        )

    def authenticate(self, token: str | None) -> AuthenticatedUser:
        if not token:
            raise CollectorError("ACCOUNT_LOGIN_REQUIRED", "PRODUCT_SESSION_REQUIRED")
        row = self.store.resolve_session(hash_secret(token), self.idle_timeout)
        if not row:
            raise CollectorError("ACCOUNT_LOGIN_REQUIRED", "PRODUCT_SESSION_INVALID")
        return AuthenticatedUser(
            user_id=str(row["user_id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"]),
            session_id=str(row["session_id"]),
            csrf_token=str(row["csrf_token"]),
        )

    def require_csrf(self, user: AuthenticatedUser, supplied: str | None) -> None:
        if not supplied or not hmac.compare_digest(user.csrf_token, supplied):
            raise CollectorError("INVALID_FORM", "CSRF_CHECK_FAILED")

    def logout(self, token: str | None, actor_user_id: str | None) -> None:
        if token:
            self.store.revoke_session(hash_secret(token), actor_user_id)
