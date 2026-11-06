from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from xingtu.contracts import PlatformRegistry
from xingtu.domain import CollectorError, CreatorScene, PlatformId, TaskStatus, uid, utcnow
from xingtu.product_api import (
    ProductServices,
    ProductSettings,
    _juxing_max_target_count,
    create_app,
)
from xingtu.product_auth import AuthService, MemoryLoginLimiter, PasswordService
from xingtu.product_covers import ProductCoverConfig
from xingtu.product_models import (
    CreateTaskResponse,
    CreatorUpdateResponse,
    CreatorUpdateServicePage,
    CreatorUpdateServiceView,
    CreatorUpdateStatus,
    TaskPage,
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
    def __init__(self):
        self.calls = []

    def list_tasks(self, **kwargs):
        self.calls.append(kwargs)
        return TaskPage(items=[], next_cursor=None)


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


class FakeUpdateServices:
    def __init__(self):
        self.calls = []

    @staticmethod
    def _view(platform="douyin_xingtu", scene=CreatorScene.VIDEO_SQUARE, enabled=True):
        return CreatorUpdateServiceView(
            platform=platform,
            creator_scene=scene,
            enabled=enabled,
            effective_enabled=False,
            scheduler_alive=False,
        )

    def list_services(self):
        return CreatorUpdateServicePage(
            items=[
                self._view("douyin_xingtu", CreatorScene.VIDEO_SQUARE, True),
                self._view("douyin_xingtu", CreatorScene.LIVE_SQUARE, False),
                self._view("kuaishou_juxing", CreatorScene.VIDEO_SQUARE, False),
                self._view("kuaishou_juxing", CreatorScene.LIVE_SQUARE, False),
            ],
            scheduler_alive=False,
        )

    def set_enabled(self, platform, scene, enabled, *, user_id):
        self.calls.append((platform, scene, enabled, user_id))
        return self._view(platform, scene, enabled)


def client_fixture(
    *,
    enable_juxing: bool = False,
    juxing_contract_path: Path | None = None,
    juxing_max_target: int = 200,
):
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
        enable_kuaishou_juxing=enable_juxing,
        juxing_observed_contract_path=(
            juxing_contract_path or Path("contracts/kuaishou_juxing.observed.json")
        ),
        juxing_registry_path=Path("contracts/kuaishou_juxing.verified.json"),
        kuaishou_juxing_max_target_count=juxing_max_target,
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
        update_services=FakeUpdateServices(),
        platform_registries={
            "kuaishou_juxing": PlatformRegistry.model_validate_json(
                settings.juxing_registry_path.read_text()
            )
        },
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


def test_task_list_platform_filter_is_forwarded_and_unknown_values_rejected():
    client, _ = client_fixture()
    login(client)
    queries = client.app.state.services.queries  # type: ignore[attr-defined]

    filtered = client.get("/api/tasks?platform=kuaishou_juxing&limit=5")
    assert filtered.status_code == 200
    assert filtered.json() == {"items": [], "next_cursor": None}
    assert queries.calls[-1]["platform"] is PlatformId.KUAISHOU_JUXING
    assert queries.calls[-1]["limit"] == 5

    unfiltered = client.get("/api/tasks")
    assert unfiltered.status_code == 200
    assert queries.calls[-1]["platform"] is None

    invalid = client.get("/api/tasks?platform=douyin_xingtu_typo")
    assert invalid.status_code == 422


def test_platform_catalog_keeps_juxing_closed_until_flag_and_verified_registry_are_present():
    client, products = client_fixture()
    csrf = login(client).json()["csrf_token"]
    response = client.get("/api/platforms")
    assert response.status_code == 200
    platforms = {item["platform"]: item for item in response.json()}
    assert platforms["douyin_xingtu"]["enabled"] is True
    assert platforms["kuaishou_juxing"]["enabled"] is False
    assert platforms["kuaishou_juxing"]["capability_status"] == "verified"
    assert platforms["kuaishou_juxing"]["disabled_reason"] == "磁力聚星功能开关当前关闭"
    creation = client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "juxing-key",
        },
        json={
            "schema_version": "requirement_form.v3",
            "platform": "kuaishou_juxing",
            "keyword": "母婴",
            "target_count": 10,
        },
    )
    assert creation.status_code == 422
    assert creation.json()["message"] == "KUAISHOU_JUXING_FEATURE_DISABLED"
    assert products.calls == []
    flagged_client, flagged_products = client_fixture(enable_juxing=True)
    flagged_csrf = login(flagged_client).json()["csrf_token"]
    flagged_catalog = {
        item["platform"]: item for item in flagged_client.get("/api/platforms").json()
    }
    assert flagged_catalog["kuaishou_juxing"]["enabled"] is True
    assert flagged_catalog["kuaishou_juxing"]["capability_status"] == "verified"
    capability = flagged_client.get("/api/platforms/kuaishou_juxing/capabilities")
    assert capability.status_code == 200
    assert capability.json()["platform"] == "kuaishou_juxing"
    assert capability.json()["target_count_default"] == 20
    assert capability.json()["target_count_max"] == 200
    flagged = flagged_client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": flagged_csrf,
            "Idempotency-Key": "juxing-flagged-key",
        },
        json={
            "schema_version": "requirement_form.v3",
            "platform": "kuaishou_juxing",
            "keyword": "母婴",
            "content_types": ["maternal_child"],
            "target_count": 70,
        },
    )
    assert flagged.status_code == 202
    assert flagged_products.calls[0][0].target_count == 70
    assert flagged_products.calls[0][1]["capability_version"] == ("juxing-video-square-stage-c-v2")


def test_juxing_target_ceiling_is_configurable_only_for_an_authorized_run():
    default_client, default_products = client_fixture(enable_juxing=True)
    default_csrf = login(default_client).json()["csrf_token"]
    accepted_70 = default_client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": default_csrf,
            "Idempotency-Key": "juxing-70-default-key",
        },
        json={
            "schema_version": "requirement_form.v3",
            "platform": "kuaishou_juxing",
            "keyword": "母婴",
            "content_types": ["maternal_child"],
            "target_count": 70,
        },
    )
    assert accepted_70.status_code == 202
    assert default_products.calls[0][0].target_count == 70
    # The form itself is still bounded by the product contract (1..200).
    over_contract = default_client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": default_csrf,
            "Idempotency-Key": "juxing-201-key",
        },
        json={
            "schema_version": "requirement_form.v3",
            "platform": "kuaishou_juxing",
            "keyword": "母婴",
            "target_count": 201,
        },
    )
    assert over_contract.status_code == 422
    assert (
        default_client.get("/api/platforms/kuaishou_juxing/capabilities").json()["target_count_max"]
        == 200
    )

    raised_client, raised_products = client_fixture(enable_juxing=True, juxing_max_target=10)
    raised_csrf = login(raised_client).json()["csrf_token"]
    raised_capability = raised_client.get("/api/platforms/kuaishou_juxing/capabilities").json()
    assert raised_capability["target_count_default"] == 10
    assert raised_capability["target_count_max"] == 10
    accepted = raised_client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": raised_csrf,
            "Idempotency-Key": "juxing-10-key",
        },
        json={
            "schema_version": "requirement_form.v3",
            "platform": "kuaishou_juxing",
            "keyword": "母婴",
            "content_types": ["maternal_child"],
            "target_count": 10,
        },
    )
    assert accepted.status_code == 202
    assert raised_products.calls[0][1]["capability_version"] == ("juxing-video-square-stage-c-v2")
    rejected = raised_client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": raised_csrf,
            "Idempotency-Key": "juxing-11-key",
        },
        json={
            "schema_version": "requirement_form.v3",
            "platform": "kuaishou_juxing",
            "keyword": "母婴",
            "target_count": 11,
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["message"] == "KUAISHOU_JUXING_TARGET_ABOVE_LIMIT"


def test_juxing_max_target_environment_is_validated(monkeypatch):
    monkeypatch.setenv("XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT", "10")
    assert _juxing_max_target_count() == 10
    monkeypatch.setenv("XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT", "0")
    with pytest.raises(CollectorError):
        _juxing_max_target_count()
    monkeypatch.setenv("XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT", "not-a-number")
    with pytest.raises(CollectorError):
        _juxing_max_target_count()
    monkeypatch.delenv("XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT")
    assert _juxing_max_target_count() == 200


def test_malformed_observed_metadata_cannot_disable_a_verified_executable_registry(tmp_path):
    malformed = tmp_path / "juxing.json"
    malformed.write_text("not-json")
    client, _ = client_fixture(enable_juxing=True, juxing_contract_path=malformed)
    login(client)
    response = client.get("/api/platforms")
    assert response.status_code == 200
    juxing = next(item for item in response.json() if item["platform"] == "kuaishou_juxing")
    assert juxing["enabled"] is True
    assert juxing["capability_status"] == "verified"


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


def test_update_services_route_requires_auth_csrf_and_reports_four_groups():
    client, _ = client_fixture()
    assert client.get("/api/update-services").status_code == 401
    login_response = login(client)
    assert login_response.status_code == 200
    csrf = login_response.json()["csrf_token"]
    page = client.get("/api/update-services")
    assert page.status_code == 200
    items = page.json()["items"]
    assert len(items) == 4
    assert {(item["platform"], item["creator_scene"]) for item in items} == {
        ("douyin_xingtu", "video_square"),
        ("douyin_xingtu", "live_square"),
        ("kuaishou_juxing", "video_square"),
        ("kuaishou_juxing", "live_square"),
    }
    assert page.json()["scheduler_alive"] is False

    missing_csrf = client.put(
        "/api/update-services/douyin_xingtu/live_square",
        headers={"Origin": "https://app.test"},
        json={"enabled": True},
    )
    assert missing_csrf.status_code == 403
    changed = client.put(
        "/api/update-services/douyin_xingtu/live_square",
        headers={"Origin": "https://app.test", "X-CSRF-Token": csrf},
        json={"enabled": True},
    )
    assert changed.status_code == 200
    assert changed.json()["enabled"] is True
    fake = client.app.state.services.update_services  # type: ignore[attr-defined]
    assert fake.calls[0][:3] == ("douyin_xingtu", CreatorScene.LIVE_SQUARE, True)

    invalid_scene = client.put(
        "/api/update-services/douyin_xingtu/unknown_scene",
        headers={"Origin": "https://app.test", "X-CSRF-Token": csrf},
        json={"enabled": True},
    )
    assert invalid_scene.status_code == 422
    invalid_platform = client.put(
        "/api/update-services/unknown_platform/video_square",
        headers={"Origin": "https://app.test", "X-CSRF-Token": csrf},
        json={"enabled": True},
    )
    assert invalid_platform.status_code == 422
