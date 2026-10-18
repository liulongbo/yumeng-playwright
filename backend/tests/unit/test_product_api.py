from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from xingtu.contracts import PlatformRegistry
from xingtu.domain import TaskStatus, uid, utcnow
from xingtu.product_api import ProductServices, ProductSettings, create_app
from xingtu.product_auth import AuthService, MemoryLoginLimiter, PasswordService
from xingtu.product_covers import ProductCoverConfig
from xingtu.product_models import (
    CreateTaskResponse,
    CreatorUpdateResponse,
    CreatorUpdateStatus,
)


class MemoryAuthStore:
    def __init__(self):
        self.passwords = PasswordService()
        self.user = {
            "user_id": uid(),
            "username": "media",
            "display_name": "媒介 A",
            "password_hash": self.passwords.hash("a-secure-password"),
            "active": True,
        }
        self.sessions = {}

    def find_user_for_login(self, username):
        return self.user if username == "media" else None

    def create_session(self, user_id, token_hash, csrf_token, idle_expires_at, absolute_expires_at):
        session_id = uid()
        self.sessions[token_hash] = {
            "session_id": session_id,
            "user_id": user_id,
            "username": "media",
            "display_name": "媒介 A",
            "csrf_token": csrf_token,
            "idle_expires_at": idle_expires_at,
            "absolute_expires_at": absolute_expires_at,
            "revoked": False,
        }
        return session_id

    def resolve_session(self, token_hash, idle_extension: timedelta):
        row = self.sessions.get(token_hash)
        if not row or row["revoked"] or row["idle_expires_at"] <= utcnow():
            return None
        row["idle_expires_at"] = min(row["absolute_expires_at"], utcnow() + idle_extension)
        return row

    def revoke_session(self, token_hash, actor_user_id):
        del actor_user_id
        if token_hash in self.sessions:
            self.sessions[token_hash]["revoked"] = True


class FakeProducts:
    def __init__(self):
        self.calls = []
        self.repository = self

    def create_product_task(self, form, **kwargs):
        self.calls.append((form, kwargs))
        return CreateTaskResponse(root_task_id="00000000-0000-0000-0000-000000000001")

    def cover_reference(self, root_task_id, object_id):
        del root_task_id, object_id
        return None


class FakeQueries:
    pass


class FakeCovers:
    def read(self, object_id, *, checksum, byte_size):
        del object_id, checksum, byte_size
        return b""


class FakeUpdates:
    def create_manual_update(self, creator_id, *, user_id, idempotency_key):
        del user_id, idempotency_key
        return CreatorUpdateResponse(root_task_id=uid(), status=TaskStatus.QUEUED)

    def status(self, creator_id):
        return CreatorUpdateStatus(creator_id=creator_id)


def client_fixture():
    auth_store = MemoryAuthStore()
    products = FakeProducts()
    settings = ProductSettings(
        database_url="unused",
        redis_url="unused",
        login_hmac_key=b"x" * 32,
        registry_path=Path("contracts/douyin_xingtu.verified.json"),
        secure_cookie=True,
        allowed_origins=("https://app.test",),
        cover_config=ProductCoverConfig(
            kind="local", directory=Path(".runtime/covers"), allowed_root=Path(".runtime")
        ),
    )
    services = ProductServices(
        auth=AuthService(
            auth_store,
            MemoryLoginLimiter(),
            passwords=auth_store.passwords,
        ),
        products=products,
        queries=FakeQueries(),
        registry=PlatformRegistry.model_validate_json(settings.registry_path.read_text()),
        covers=FakeCovers(),
        settings=settings,
        updates=FakeUpdates(),
    )
    return TestClient(create_app(services), base_url="https://app.test"), products


def login(client):
    return client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": "media", "password": "a-secure-password"},
    )


def test_login_cookie_me_logout_and_origin_csrf_protection():
    client, _ = client_fixture()
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "media", "password": "a-secure-password"},
        ).status_code
        == 403
    )
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    csrf = response.json()["csrf_token"]
    assert client.get("/api/auth/me").status_code == 200
    assert (
        client.post("/api/auth/logout", headers={"Origin": "https://app.test"}).status_code == 403
    )
    assert (
        client.post(
            "/api/auth/logout",
            headers={"Origin": "https://app.test", "X-CSRF-Token": csrf},
        ).status_code
        == 204
    )
    assert client.get("/api/auth/me").status_code == 401


def test_capabilities_and_task_submission_require_session_and_csrf():
    client, products = client_fixture()
    assert client.get("/api/platforms/douyin_xingtu/capabilities").status_code == 401
    auth = login(client)
    csrf = auth.json()["csrf_token"]
    capability = client.get("/api/platforms/douyin_xingtu/capabilities")
    assert capability.status_code == 200
    assert [field["field"] for field in capability.json()["fields"]] == [
        "keyword",
        "gender",
        "region",
        "education",
        "yellow_v",
        "connection_users",
        "followers",
        "viewer_profile",
        "fan_profile",
    ]
    region = next(field for field in capability.json()["fields"] if field["field"] == "region")
    assert len(region["region_tree"]) == 34
    body = {"keyword": "宠物", "target_count": 20}
    assert (
        client.post(
            "/api/tasks",
            headers={"Origin": "https://app.test", "Idempotency-Key": "key"},
            json=body,
        ).status_code
        == 403
    )
    response = client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "key",
        },
        json=body,
    )
    assert response.status_code == 202
    assert len(products.calls) == 1
    assert products.calls[0][0].schema_version == "requirement_form.v2"


def test_api_validation_uses_unified_error_and_strict_target_count():
    client, _ = client_fixture()
    csrf = login(client).json()["csrf_token"]
    response = client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "key",
        },
        json={"keyword": "宠物", "target_count": "20"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_FORM"
    assert response.json()["field_errors"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/tasks",
        "/api/tasks/root",
        "/api/tasks/root/creators",
        "/api/tasks/root/creators/creator",
        "/api/tasks/root/creators/creator/contents?collection_type=excellent_reach",
        "/api/tasks/root/covers/cover/root/checksum",
    ],
)
def test_every_business_read_including_cover_requires_authentication(path):
    client, _ = client_fixture()
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["code"] == "ACCOUNT_LOGIN_REQUIRED"


def test_creator_update_routes_use_csrf_and_are_authenticated():
    client, _ = client_fixture()
    assert (
        client.post(
            "/api/creator-library/creator/updates",
            headers={"Origin": "https://app.test", "Idempotency-Key": "k"},
        ).status_code
        == 401
    )
    login_response = login(client)
    assert login_response.status_code == 200
    csrf = login_response.json()["csrf_token"]
    missing_key = client.post(
        "/api/creator-library/creator/updates",
        headers={"Origin": "https://app.test", "X-CSRF-Token": csrf},
    )
    assert missing_key.status_code == 422
    response = client.post(
        "/api/creator-library/creator/updates",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "k",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    status = client.get("/api/creator-library/creator/update")
    assert status.status_code == 200
    assert status.json()["creator_id"] == "creator"
