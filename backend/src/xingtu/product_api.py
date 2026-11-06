import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import Cookie, Depends, FastAPI, Header, Query, Request, Response, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from redis import Redis
from starlette.middleware.base import RequestResponseEndpoint

from .adapter_factory import (
    platform_adapter_available,
    platform_scene_adapter_available,
)
from .contracts import PlatformRegistry
from .creator_update import CreatorUpdateService
from .creator_update_services import CreatorUpdateServiceAdmin
from .domain import (
    CollectorError,
    CreatorScene,
    PlatformId,
    ProfileRequirement,
    TaskKind,
    TaskStatus,
)
from .live_update import LiveCreatorUpdateService
from .product_auth import AuthService, RedisLoginLimiter
from .product_covers import ProductCoverConfig, ProductCoverReader
from .product_models import (
    AuthenticatedUser,
    BrowserTakeoverView,
    CommandRequest,
    CreateTaskResponse,
    CreatorLibraryDetail,
    CreatorLibraryHistory,
    CreatorLibraryPage,
    CreatorLibraryQuote,
    CreatorPage,
    CreatorSummary,
    CreatorUpdateResponse,
    CreatorUpdateServicePage,
    CreatorUpdateServicePatch,
    CreatorUpdateServiceView,
    CreatorUpdateStatus,
    CreatorVideoPage,
    ExecutionUnitView,
    FieldError,
    LoginRequest,
    ProductError,
    ProfileFieldCatalog,
    RequirementForm,
    TaskDetail,
    TaskPage,
    UserView,
    VerificationEventView,
)
from .product_queries import ProductQueries
from .product_repository import ProductRepository
from .profile_catalog import build_profile_field_catalog
from .repository import Repository
from .worker_health import INTAKE_QUEUE, WorkerHealthMonitor

SESSION_COOKIE = "xingtu_product_session"
CSRF_HEADER = "X-CSRF-Token"


def _juxing_max_target_count() -> int:
    """Configured juxing target ceiling; the default follows the product contract (200).

    The stage-B safety default of 3 was removed once the product contract and the verified
    page-fetch boundary allowed a real 70-creator acceptance.  A deployment that needs a lower
    ceiling must set ``XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT`` explicitly.
    """

    raw = os.environ.get("XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT", "200")
    try:
        value = int(raw)
    except ValueError:
        raise CollectorError(
            "STORAGE_UNAVAILABLE", "KUAISHOU_JUXING_MAX_TARGET_COUNT_INVALID"
        ) from None
    if not 1 <= value <= 200:
        raise CollectorError("STORAGE_UNAVAILABLE", "KUAISHOU_JUXING_MAX_TARGET_COUNT_INVALID")
    return value


@dataclass(frozen=True)
class ProductSettings:
    database_url: str
    redis_url: str
    login_hmac_key: bytes
    registry_path: Path
    model_config_id: str = "deepseek-flash"
    prompt_version: str = "m3-filter-plan-v2"
    secure_cookie: bool = True
    allowed_origins: tuple[str, ...] = ()
    cover_config: ProductCoverConfig | None = None
    temporal_address: str = "127.0.0.1:57233"
    remote_viewer_base_url: str | None = None
    remote_vnc_targets: dict[str, str] | None = None
    profile_requirement_path: Path = Path("contracts/profile_requirements.json")
    enable_kuaishou_juxing: bool = False
    enable_live_square: bool = False
    xingtu_live_registry_path: Path = Path("contracts/douyin_xingtu.live.verified.json")
    juxing_live_registry_path: Path = Path("contracts/kuaishou_juxing.live.verified.json")
    juxing_observed_contract_path: Path = Path("contracts/kuaishou_juxing.observed.json")
    juxing_registry_path: Path = Path("contracts/kuaishou_juxing.verified.json")
    # Product ceiling shared with Xingtu. The previous stage-B default of 3 was a safety limit,
    # not a product decision; keeping it here would silently cap a deployment without the env var.
    kuaishou_juxing_max_target_count: int = 200

    @classmethod
    def from_environment(cls) -> "ProductSettings":
        database_url = os.environ.get("XINGTU_DATABASE_URL", "")
        redis_url = os.environ.get("XINGTU_REDIS_URL", "")
        hmac_key = os.environ.get("XINGTU_LOGIN_HMAC_KEY", "")
        registry_path = Path(
            os.environ.get("XINGTU_REGISTRY_PATH", "contracts/douyin_xingtu.verified.json")
        )
        if not database_url:
            raise CollectorError("STORAGE_UNAVAILABLE", "XINGTU_DATABASE_URL_REQUIRED")
        if not redis_url:
            raise CollectorError("STORAGE_UNAVAILABLE", "XINGTU_REDIS_URL_REQUIRED")
        if len(hmac_key.encode()) < 32:
            raise CollectorError("STORAGE_UNAVAILABLE", "XINGTU_LOGIN_HMAC_KEY_TOO_SHORT")
        origins = tuple(
            item.strip()
            for item in os.environ.get("XINGTU_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        )
        secure = os.environ.get("XINGTU_SECURE_COOKIE", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        runtime_root = Path(os.environ.get("XINGTU_RUNTIME_ROOT", ".runtime")).resolve()
        cover_kind = os.environ.get("XINGTU_COVER_KIND", "local")
        if cover_kind == "s3":
            cover_config = ProductCoverConfig(
                kind="s3",
                endpoint=os.environ.get("XINGTU_S3_ENDPOINT"),
                bucket=os.environ.get("XINGTU_S3_COVER_BUCKET"),
            )
        else:
            cover_config = ProductCoverConfig(
                kind="local",
                directory=Path(
                    os.environ.get("XINGTU_COVER_DIRECTORY", str(runtime_root / "covers"))
                ),
                allowed_root=runtime_root,
            )
        remote_viewer_base_url = os.environ.get("XINGTU_REMOTE_VIEWER_BASE_URL") or None
        if remote_viewer_base_url and (
            not remote_viewer_base_url.startswith("/") or remote_viewer_base_url.startswith("//")
        ):
            raise CollectorError("STORAGE_UNAVAILABLE", "REMOTE_VIEWER_MUST_BE_SAME_ORIGIN_PATH")
        raw_vnc_targets = os.environ.get("XINGTU_REMOTE_VNC_TARGETS_JSON", "{}")
        try:
            remote_vnc_targets = json.loads(raw_vnc_targets)
        except json.JSONDecodeError as exc:
            raise CollectorError("STORAGE_UNAVAILABLE", "REMOTE_VNC_TARGETS_INVALID") from exc
        if not isinstance(remote_vnc_targets, dict) or not all(
            isinstance(unit, str) and isinstance(target, str) and ":" in target
            for unit, target in remote_vnc_targets.items()
        ):
            raise CollectorError("STORAGE_UNAVAILABLE", "REMOTE_VNC_TARGETS_INVALID")
        return cls(
            database_url=database_url,
            redis_url=redis_url,
            login_hmac_key=hmac_key.encode(),
            registry_path=registry_path,
            model_config_id=os.environ.get("XINGTU_DEEPSEEK_MODEL", "deepseek-flash"),
            prompt_version=os.environ.get("XINGTU_PROMPT_VERSION", "m3-filter-plan-v2"),
            secure_cookie=secure,
            allowed_origins=origins,
            cover_config=cover_config,
            temporal_address=os.environ.get("XINGTU_TEMPORAL_ADDRESS", "127.0.0.1:57233"),
            remote_viewer_base_url=remote_viewer_base_url,
            remote_vnc_targets=remote_vnc_targets,
            profile_requirement_path=Path(
                os.environ.get(
                    "XINGTU_PROFILE_REQUIREMENT_PATH",
                    "contracts/profile_requirements.json",
                )
            ),
            enable_kuaishou_juxing=os.environ.get("XINGTU_ENABLE_KUAISHOU_JUXING", "0").lower()
            in {"1", "true", "yes"},
            enable_live_square=os.environ.get("XINGTU_ENABLE_LIVE_SQUARE", "0").lower()
            in {"1", "true", "yes"},
            xingtu_live_registry_path=Path(
                os.environ.get(
                    "XINGTU_LIVE_REGISTRY_PATH",
                    "contracts/douyin_xingtu.live.verified.json",
                )
            ),
            juxing_live_registry_path=Path(
                os.environ.get(
                    "XINGTU_JUXING_LIVE_REGISTRY_PATH",
                    "contracts/kuaishou_juxing.live.verified.json",
                )
            ),
            juxing_observed_contract_path=Path(
                os.environ.get(
                    "XINGTU_JUXING_OBSERVED_CONTRACT_PATH",
                    "contracts/kuaishou_juxing.observed.json",
                )
            ),
            juxing_registry_path=Path(
                os.environ.get(
                    "XINGTU_JUXING_REGISTRY_PATH",
                    "contracts/kuaishou_juxing.verified.json",
                )
            ),
            kuaishou_juxing_max_target_count=_juxing_max_target_count(),
        )


@dataclass
class ProductServices:
    auth: AuthService
    products: ProductRepository
    queries: ProductQueries
    registry: PlatformRegistry
    covers: ProductCoverReader
    settings: ProductSettings
    updates: CreatorUpdateService | None = None
    live_updates: LiveCreatorUpdateService | None = None
    update_services: CreatorUpdateServiceAdmin | None = None
    platform_registries: dict[str, PlatformRegistry] = field(default_factory=dict)
    live_registries: dict[str, PlatformRegistry] = field(default_factory=dict)

    def registry_for(self, platform: str) -> PlatformRegistry:
        if platform == "douyin_xingtu":
            return self.registry
        registry = self.platform_registries.get(platform)
        if registry is None:
            raise CollectorError("UNSUPPORTED_FILTER", "PLATFORM_CONTRACT_NOT_AVAILABLE")
        return registry

    def registry_for_scene(self, platform: str, scene: CreatorScene | str) -> PlatformRegistry:
        value = CreatorScene(scene) if isinstance(scene, str) else scene
        if value == CreatorScene.VIDEO_SQUARE:
            return self.registry_for(platform)
        registry = self.live_registries.get(f"{platform}:{value.value}")
        if registry is None:
            raise CollectorError("UNSUPPORTED_FILTER", "LIVE_CONTRACT_NOT_AVAILABLE")
        return registry


def build_services(
    settings: ProductSettings, worker_health: WorkerHealthMonitor | None = None
) -> ProductServices:
    repository = Repository(settings.database_url)
    products = ProductRepository(repository)
    limiter = RedisLoginLimiter(
        Redis.from_url(settings.redis_url, decode_responses=True), settings.login_hmac_key
    )
    auth = AuthService(products, limiter)
    registry = PlatformRegistry.model_validate_json(settings.registry_path.read_text())
    registry.require_enabled(live=True)
    platform_registries: dict[str, PlatformRegistry] = {}
    if settings.juxing_registry_path.is_file():
        try:
            juxing_registry = PlatformRegistry.model_validate_json(
                settings.juxing_registry_path.read_text()
            )
            juxing_registry.require_enabled(live=True)
        except (OSError, ValueError) as exc:
            if settings.enable_kuaishou_juxing:
                raise CollectorError(
                    "STORAGE_UNAVAILABLE", "KUAISHOU_JUXING_REGISTRY_INVALID"
                ) from exc
        else:
            platform_registries["kuaishou_juxing"] = juxing_registry
    elif settings.enable_kuaishou_juxing:
        raise CollectorError("STORAGE_UNAVAILABLE", "KUAISHOU_JUXING_REGISTRY_INVALID")
    live_registries: dict[str, PlatformRegistry] = {}
    for platform, path in (
        ("douyin_xingtu", settings.xingtu_live_registry_path),
        ("kuaishou_juxing", settings.juxing_live_registry_path),
    ):
        if not path.is_file():
            continue
        try:
            live_registry = PlatformRegistry.model_validate_json(path.read_text())
            live_registry.require_enabled(live=True)
        except (OSError, ValueError) as exc:
            if settings.enable_live_square:
                raise CollectorError(
                    "STORAGE_UNAVAILABLE", f"{platform}_LIVE_REGISTRY_INVALID"
                ) from exc
            continue
        live_registries[f"{platform}:{CreatorScene.LIVE_SQUARE.value}"] = live_registry
    requirement = (
        ProfileRequirement.model_validate_json(settings.profile_requirement_path.read_text())
        if settings.profile_requirement_path.is_file()
        else None
    )
    return ProductServices(
        auth=auth,
        products=products,
        queries=ProductQueries(repository, worker_health),
        registry=registry,
        covers=ProductCoverReader(settings.cover_config or ProductCoverConfig()),
        settings=settings,
        updates=CreatorUpdateService(repository, registry, requirement),
        live_updates=LiveCreatorUpdateService(repository, live_registries),
        update_services=CreatorUpdateServiceAdmin(repository),
        platform_registries=platform_registries,
        live_registries=live_registries,
    )


def _status_for_error(exc: CollectorError) -> int:
    if exc.code == "ACCOUNT_LOGIN_REQUIRED":
        return 401
    if exc.reason in {"CSRF_CHECK_FAILED", "ORIGIN_CHECK_FAILED", "TAKEOVER_ACCESS_DENIED"}:
        return 403
    if exc.reason in {
        "TASK_NOT_FOUND",
        "CREATOR_NOT_FOUND",
        "COVER_NOT_FOUND",
        "TAKEOVER_NOT_FOUND",
        "VERIFICATION_EVENT_NOT_FOUND",
        "EXECUTION_UNIT_NOT_FOUND",
    }:
        return 404
    if exc.reason in {
        "IDEMPOTENCY_CONFLICT",
        "STATE_VERSION_CONFLICT",
        "ACTION_NOT_ALLOWED",
        "NO_RETRYABLE_FAILURE",
        "INTAKE_STATE_CONFLICT",
        "BROWSER_ALREADY_TAKEN_OVER",
        "NO_ACTIVE_VERIFICATION_EVENT",
        "TAKEOVER_NOT_ACTIVE",
        "TAKEOVER_NOT_RELEASABLE",
    }:
        return 409
    if exc.code == "PLATFORM_RATE_LIMITED":
        return 429
    if exc.code in {"RESOURCE_UNAVAILABLE", "STORAGE_UNAVAILABLE"}:
        return 503
    return 422


def create_app(
    services: ProductServices | None = None,
    worker_health: WorkerHealthMonitor | None = None,
) -> FastAPI:
    if services is None:
        settings = ProductSettings.from_environment()
        if worker_health is None:
            worker_health = WorkerHealthMonitor(settings.temporal_address, [INTAKE_QUEUE])
        services = build_services(settings, worker_health)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        if worker_health is not None:
            worker_health.start()
        try:
            yield
        finally:
            if worker_health is not None:
                worker_health.stop()

    app = FastAPI(title="巨量星图达人采集产品 API", version="0.3.0", lifespan=lifespan)
    app.state.services = services
    app.state.worker_health = worker_health

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(CollectorError)
    async def collector_error(request: Request, exc: CollectorError) -> JSONResponse:
        status_code = _status_for_error(exc)
        current_version = None
        current_actions: list[str] = []
        root_task_id = request.path_params.get("root_task_id")
        if status_code == 409 and root_task_id:
            try:
                current = services.queries.get_task(root_task_id)
            except CollectorError:
                pass
            else:
                current_version = current.version
                current_actions = current.allowed_actions
        body = ProductError(
            code=exc.code,
            message=exc.reason or exc.code,
            request_id=request.state.request_id,
            current_version=current_version,
            allowed_actions=current_actions,
        )
        return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        field_errors = [
            FieldError(
                code="INVALID_FORM",
                path=".".join(str(item) for item in error["loc"]),
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        body = ProductError(
            code="INVALID_FORM",
            message="请求格式不合法",
            field_errors=field_errors,
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    def require_origin(request: Request) -> None:
        origin = request.headers.get("Origin")
        if not origin or origin not in services.settings.allowed_origins:
            raise CollectorError("INVALID_FORM", "ORIGIN_CHECK_FAILED")

    def current_user(
        token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> AuthenticatedUser:
        return services.auth.authenticate(token)

    def current_user_with_csrf(
        request: Request,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        csrf: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
    ) -> AuthenticatedUser:
        require_origin(request)
        services.auth.require_csrf(user, csrf)
        return user

    @app.post("/api/auth/login", response_model=UserView)
    def login(body: LoginRequest, request: Request, response: Response) -> UserView:
        require_origin(request)
        ip_address = request.client.host if request.client else "unknown"
        new_session = services.auth.login(body.username, body.password, ip_address)
        response.set_cookie(
            SESSION_COOKIE,
            new_session.token,
            httponly=True,
            secure=services.settings.secure_cookie,
            samesite="lax",
            path="/",
            max_age=7 * 24 * 60 * 60,
        )
        return UserView(
            user_id=new_session.user.user_id,
            username=new_session.user.username,
            display_name=new_session.user.display_name,
            csrf_token=new_session.user.csrf_token,
        )

    @app.post("/api/auth/logout", status_code=204)
    def logout(
        request: Request,
        response: Response,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
        token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> None:
        services.auth.logout(token, user.user_id)
        response.delete_cookie(SESSION_COOKIE, path="/")

    @app.get("/api/auth/me", response_model=UserView)
    def me(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> UserView:
        return UserView(
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            csrf_token=user.csrf_token,
        )

    @app.get("/api/platforms/{platform}/capabilities")
    def capabilities(
        platform: Literal["douyin_xingtu", "kuaishou_juxing"],
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE,
    ) -> dict[str, Any]:
        del user
        from .product_models import CapabilityDTO

        if platform == "kuaishou_juxing" and not services.settings.enable_kuaishou_juxing:
            raise CollectorError("UNSUPPORTED_FILTER", "KUAISHOU_JUXING_FEATURE_DISABLED")
        if creator_scene == CreatorScene.LIVE_SQUARE and not services.settings.enable_live_square:
            raise CollectorError("UNSUPPORTED_FILTER", "LIVE_SQUARE_FEATURE_DISABLED")
        registry = services.registry_for_scene(platform, creator_scene)
        return CapabilityDTO.from_capabilities(
            registry.capabilities,
            platform=platform,
            creator_scene=creator_scene,
            target_count_max=(
                70
                if creator_scene == CreatorScene.LIVE_SQUARE
                else (
                    services.settings.kuaishou_juxing_max_target_count
                    if platform == "kuaishou_juxing"
                    else None
                )
            ),
        ).model_dump(mode="json")

    @app.get("/api/platforms")
    def platforms(
        user: Annotated[AuthenticatedUser, Depends(current_user)],
    ) -> list[dict[str, Any]]:
        del user
        observed_status = "unavailable"
        observed_version = None
        path = services.settings.juxing_observed_contract_path
        if path.is_file():
            try:
                metadata = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                metadata = {}
            candidate_status = str(metadata.get("status") or "unavailable")
            if candidate_status in {"verified", "observed", "documented", "unavailable"}:
                observed_status = candidate_status
            observed_version = (
                metadata.get("contract_version")
                if isinstance(metadata.get("contract_version"), str)
                else None
            )
        executable_registry = services.platform_registries.get("kuaishou_juxing")
        executable_verified = executable_registry is not None
        # A feature flag alone cannot upgrade observed evidence or enable live collection.
        juxing_enabled = (
            services.settings.enable_kuaishou_juxing
            and executable_verified
            and platform_adapter_available("kuaishou_juxing")
        )
        if not services.settings.enable_kuaishou_juxing:
            juxing_disabled_reason = "磁力聚星功能开关当前关闭"
        elif not executable_verified:
            juxing_disabled_reason = "磁力聚星可执行能力合同不可用"
        elif not platform_adapter_available("kuaishou_juxing"):
            juxing_disabled_reason = "当前构建尚未包含可执行的磁力聚星 Adapter"
        else:
            juxing_disabled_reason = None

        def scenes_for(platform: str, video_registry: PlatformRegistry) -> list[dict[str, Any]]:
            live = services.live_registries.get(f"{platform}:live_square")
            live_enabled = bool(
                services.settings.enable_live_square
                and live is not None
                and platform_scene_adapter_available(platform, CreatorScene.LIVE_SQUARE)
            )
            if platform == "kuaishou_juxing" and not services.settings.enable_kuaishou_juxing:
                live_enabled = False
            reason = None
            if not services.settings.enable_live_square:
                reason = "直播广场功能开关当前关闭"
            elif live is None:
                reason = "直播广场可执行能力合同不可用"
            elif not platform_scene_adapter_available(platform, CreatorScene.LIVE_SQUARE):
                reason = "当前构建尚未包含可执行的直播 Adapter"
            return [
                {
                    "scene": "video_square",
                    "label": "短视频广场",
                    "enabled": True,
                    "capability_status": "verified",
                    "contract_version": video_registry.contract_version,
                },
                {
                    "scene": "live_square",
                    "label": "直播广场",
                    "enabled": live_enabled,
                    "capability_status": "verified" if live is not None else "unavailable",
                    "contract_version": live.contract_version if live is not None else None,
                    "disabled_reason": reason,
                },
            ]

        return [
            {
                "platform": "douyin_xingtu",
                "label": "巨量星图",
                "enabled": True,
                "capability_status": "verified",
                "contract_version": services.registry.contract_version,
                "scenes": scenes_for("douyin_xingtu", services.registry),
            },
            {
                "platform": "kuaishou_juxing",
                "label": "磁力聚星",
                "enabled": juxing_enabled,
                "capability_status": "verified" if executable_verified else observed_status,
                "contract_version": (
                    executable_registry.contract_version
                    if executable_registry is not None
                    else observed_version
                ),
                "disabled_reason": juxing_disabled_reason,
                "scenes": scenes_for(
                    "kuaishou_juxing",
                    executable_registry or services.registry,
                ),
            },
        ]

    @app.get(
        "/api/platforms/{platform}/profile-field-catalog",
        response_model=ProfileFieldCatalog,
    )
    def profile_field_catalog(
        platform: Literal["douyin_xingtu", "kuaishou_juxing"],
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE,
    ) -> ProfileFieldCatalog:
        """Display names, kinds and registered units for one platform's profile fields.

        Read-only projection of the already-loaded verified registry: no database access, no
        business values.  Evidence-corrected display names are marked with `name_source`.
        """

        del user
        return build_profile_field_catalog(
            services.registry_for_scene(platform, creator_scene), platform
        )

    @app.post("/api/tasks", response_model=CreateTaskResponse, status_code=202)
    def create_task(
        form: RequirementForm,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        origin_root_task_id: Annotated[UUID | None, Header(alias="X-Origin-Root-Task-Id")] = None,
    ) -> CreateTaskResponse:
        if form.platform == "kuaishou_juxing":
            if not services.settings.enable_kuaishou_juxing:
                raise CollectorError("UNSUPPORTED_FILTER", "KUAISHOU_JUXING_FEATURE_DISABLED")
            if form.target_count > services.settings.kuaishou_juxing_max_target_count:
                raise CollectorError("UNSUPPORTED_FILTER", "KUAISHOU_JUXING_TARGET_ABOVE_LIMIT")
        if form.creator_scene == CreatorScene.LIVE_SQUARE:
            if not services.settings.enable_live_square:
                raise CollectorError("UNSUPPORTED_FILTER", "LIVE_SQUARE_FEATURE_DISABLED")
            if form.target_count > 70:
                raise CollectorError("UNSUPPORTED_FILTER", "LIVE_TARGET_ABOVE_LIMIT")
        registry = services.registry_for_scene(form.platform, form.creator_scene)
        return services.products.create_product_task(
            form,
            capability_version=registry.capabilities.version,
            user_id=user.user_id,
            idempotency_key=idempotency_key,
            model_config_id=services.settings.model_config_id,
            prompt_version=services.settings.prompt_version,
            origin_root_task_id=str(origin_root_task_id) if origin_root_task_id else None,
        )

    @app.get("/api/tasks", response_model=TaskPage)
    def list_tasks(
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        status: TaskStatus | None = None,
        task_kind: TaskKind | None = None,
        platform: Literal["douyin_xingtu", "kuaishou_juxing"] | None = None,
        creator_scene: CreatorScene | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> TaskPage:
        del user
        return services.queries.list_tasks(
            status=status,
            task_kind=task_kind,
            platform=PlatformId(platform) if platform else None,
            creator_scene=creator_scene,
            created_from=created_from,
            created_to=created_to,
            cursor=cursor,
            limit=limit,
        )

    @app.get("/api/tasks/{root_task_id}", response_model=TaskDetail)
    def task_detail(
        root_task_id: str, user: Annotated[AuthenticatedUser, Depends(current_user)]
    ) -> TaskDetail:
        del user
        return services.queries.get_task(root_task_id)

    @app.get("/api/health/workers")
    def workers_health(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> dict[str, Any]:
        """Report which task queues currently have a live consumer.

        A poller entry is only counted as live while its last access is fresh, because Temporal
        keeps disconnected pollers listed for minutes.
        """
        del user
        snapshot = worker_health.snapshot() if worker_health else {}
        return {
            "temporal_address": services.settings.temporal_address,
            "queues": {
                queue: {
                    "alive": health.alive,
                    "fresh_pollers": health.fresh_pollers,
                    "poller_entries": health.poller_entries,
                    "freshest_age_seconds": health.freshest_age_seconds,
                    "checked_at": health.checked_at.isoformat(),
                    "error": health.error,
                }
                for queue, health in snapshot.items()
            },
        }

    def takeover_view(row: dict[str, Any]) -> BrowserTakeoverView:
        viewer_url = None
        access_mode: Literal["LOCAL_WINDOW", "REMOTE_VIEWER"] = "LOCAL_WINDOW"
        operator_message = "请切换到本机已经打开的执行单元 Chrome 窗口完成验证。"
        if row["state"] == "ACTIVE" and services.settings.remote_viewer_base_url:
            # The configured viewer is a same-origin noVNC client. It authenticates the WebSocket
            # separately; no VNC address, debug port or credential is returned here.
            viewer_url = (
                services.settings.remote_viewer_base_url.rstrip("/")
                + "?takeover_id="
                + str(row["takeover_id"])
            )
            access_mode = "REMOTE_VIEWER"
            operator_message = "请在下方受认证的远程浏览器中完成验证。"
        return services.queries.takeover_view(
            row,
            viewer_url=viewer_url,
            access_mode=access_mode,
            operator_message=operator_message,
        )

    async def proxy_original_vnc(websocket: WebSocket, takeover_id: str) -> None:
        """Proxy RFB bytes only for the operator's currently ACTIVE original browser.

        The target is an allow-listed private-network address from deployment configuration. It is
        never sent to the browser, and the stream closes before the Worker runs Playwright's
        read-only verification after an operator submits completion.
        """
        if websocket.headers.get("origin") not in services.settings.allowed_origins:
            await websocket.close(code=1008)
            return
        try:
            user = services.auth.authenticate(websocket.cookies.get(SESSION_COOKIE))
            takeover = services.queries.repository.active_takeover_for_viewer(
                takeover_id, user.user_id
            )
        except CollectorError:
            await websocket.close(code=1008)
            return
        target = (services.settings.remote_vnc_targets or {}).get(str(takeover["unit_id"]))
        host, separator, raw_port = target.rpartition(":") if target else ("", "", "")
        if not separator or not host or not raw_port.isdigit():
            await websocket.close(code=1013)
            return
        try:
            reader, writer = await asyncio.open_connection(host, int(raw_port))
        except OSError:
            await websocket.close(code=1013)
            return
        connection_id = str(uuid4())
        try:
            services.queries.repository.claim_takeover_viewer(
                takeover_id, user.user_id, connection_id
            )
        except CollectorError:
            writer.close()
            await writer.wait_closed()
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def vnc_to_viewer() -> None:
            while chunk := await reader.read(65536):
                await websocket.send_bytes(chunk)

        async def viewer_to_vnc() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if payload := message.get("bytes"):
                    writer.write(payload)
                    await writer.drain()

        async def active_guard() -> None:
            while True:
                await asyncio.sleep(1)
                try:
                    services.queries.repository.active_takeover_for_viewer(
                        takeover_id, user.user_id
                    )
                except CollectorError:
                    return

        tasks = [
            asyncio.create_task(vnc_to_viewer()),
            asyncio.create_task(viewer_to_vnc()),
            asyncio.create_task(active_guard()),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            await writer.wait_closed()
            try:
                services.queries.repository.release_takeover_viewer(takeover_id, connection_id)
            finally:
                with suppress(RuntimeError):
                    await websocket.close()

    @app.websocket("/api/takeovers/{takeover_id}/viewer")
    async def original_browser_viewer(websocket: WebSocket, takeover_id: str) -> None:
        await proxy_original_vnc(websocket, takeover_id)

    @app.get("/api/execution-units", response_model=list[ExecutionUnitView])
    def execution_units(
        user: Annotated[AuthenticatedUser, Depends(current_user)],
    ) -> list[ExecutionUnitView]:
        del user
        return services.queries.list_execution_units()

    @app.get("/api/execution-units/{unit_id}", response_model=ExecutionUnitView)
    def execution_unit(
        unit_id: str, user: Annotated[AuthenticatedUser, Depends(current_user)]
    ) -> ExecutionUnitView:
        del user
        return services.queries.execution_unit(unit_id)

    @app.get("/api/update-services", response_model=CreatorUpdateServicePage)
    def update_services(
        user: Annotated[AuthenticatedUser, Depends(current_user)],
    ) -> CreatorUpdateServicePage:
        del user
        admin = services.update_services
        if admin is None:
            raise CollectorError("STORAGE_UNAVAILABLE", "UPDATE_SERVICES_NOT_CONFIGURED")
        return admin.list_services()

    @app.put(
        "/api/update-services/{platform}/{creator_scene}",
        response_model=CreatorUpdateServiceView,
    )
    def set_update_service(
        platform: Literal["douyin_xingtu", "kuaishou_juxing"],
        creator_scene: CreatorScene,
        body: CreatorUpdateServicePatch,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
    ) -> CreatorUpdateServiceView:
        admin = services.update_services
        if admin is None:
            raise CollectorError("STORAGE_UNAVAILABLE", "UPDATE_SERVICES_NOT_CONFIGURED")
        return admin.set_enabled(platform, creator_scene, body.enabled, user_id=user.user_id)

    @app.get("/api/verification-events", response_model=list[VerificationEventView])
    def verification_events(
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        open_only: bool = True,
    ) -> list[VerificationEventView]:
        del user
        return services.queries.verification_events(open_only=open_only)

    @app.post(
        "/api/execution-units/{unit_id}/takeovers",
        response_model=BrowserTakeoverView,
        status_code=202,
    )
    def request_takeover(
        unit_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
    ) -> BrowserTakeoverView:
        takeover = services.queries.repository.request_browser_takeover(unit_id, user.user_id)
        return takeover_view(takeover)

    @app.get("/api/takeovers/{takeover_id}", response_model=BrowserTakeoverView)
    def takeover_status(
        takeover_id: str, user: Annotated[AuthenticatedUser, Depends(current_user)]
    ) -> BrowserTakeoverView:
        return takeover_view(services.queries.repository.takeover(takeover_id, user.user_id))

    @app.post("/api/takeovers/{takeover_id}/reappearance", response_model=BrowserTakeoverView)
    def takeover_reappearance(
        takeover_id: str,
        reason: Literal[
            "PLATFORM_SECURITY_CHALLENGE",
            "ACCOUNT_LOGIN_REQUIRED",
            "ACCOUNT_MISMATCH",
            "NETWORK_OR_PROTECTED_PAGE_UNAVAILABLE",
            "HUMAN_CANNOT_COMPLETE",
        ],
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
    ) -> BrowserTakeoverView:
        return takeover_view(
            services.queries.repository.report_takeover_reappearance(
                takeover_id, user.user_id, reason
            )
        )

    @app.post(
        "/api/takeovers/{takeover_id}/complete",
        response_model=BrowserTakeoverView,
        status_code=202,
    )
    def complete_takeover(
        takeover_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
    ) -> BrowserTakeoverView:
        return takeover_view(
            services.queries.repository.complete_browser_takeover(takeover_id, user.user_id)
        )

    @app.delete("/api/takeovers/{takeover_id}", status_code=204)
    def release_takeover(
        takeover_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
    ) -> None:
        services.queries.repository.release_browser_takeover(takeover_id, user.user_id)

    def execute_command(
        action: Literal["cancel", "continue", "retry"],
        root_task_id: str,
        body: CommandRequest,
        user: AuthenticatedUser,
        idempotency_key: str,
    ) -> TaskDetail:
        return services.queries.command(
            root_task_id,
            action,
            expected_version=body.expected_version,
            user_id=user.user_id,
            idempotency_key=idempotency_key,
        )

    @app.post("/api/tasks/{root_task_id}/cancel", response_model=TaskDetail)
    def cancel_task(
        root_task_id: str,
        body: CommandRequest,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> TaskDetail:
        return execute_command("cancel", root_task_id, body, user, idempotency_key)

    @app.post("/api/tasks/{root_task_id}/continue", response_model=TaskDetail)
    def continue_task(
        root_task_id: str,
        body: CommandRequest,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> TaskDetail:
        return execute_command("continue", root_task_id, body, user, idempotency_key)

    @app.post("/api/tasks/{root_task_id}/retry", response_model=TaskDetail)
    def retry_task(
        root_task_id: str,
        body: CommandRequest,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> TaskDetail:
        return execute_command("retry", root_task_id, body, user, idempotency_key)

    @app.get("/api/tasks/{root_task_id}/creators", response_model=CreatorPage)
    def creators(
        root_task_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> CreatorPage:
        del user
        return services.queries.list_creators(root_task_id, cursor=cursor, limit=limit)

    @app.get("/api/tasks/{root_task_id}/creators/{creator_id}", response_model=CreatorSummary)
    def creator_detail(
        root_task_id: str,
        creator_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
    ) -> CreatorSummary:
        del user
        return services.queries.get_creator(root_task_id, creator_id)

    @app.get("/api/tasks/{root_task_id}/creators/{creator_id}/contents")
    def creator_contents(
        root_task_id: str,
        creator_id: str,
        collection_type: Literal["excellent_reach", "excellent_seeding"],
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        del user
        return services.queries.contents(
            root_task_id,
            creator_id,
            collection_type,
            cursor=cursor,
            limit=limit,
        )

    @app.get("/api/creator-library", response_model=CreatorLibraryPage)
    def creator_library(
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu",
        creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE,
        industry: str | None = None,
        creator_type: str | None = None,
        province: str | None = None,
        city: str | None = None,
        followers_min: Annotated[float | None, Query(ge=0)] = None,
        followers_max: Annotated[float | None, Query(ge=0)] = None,
        monthly_growth_min: float | None = None,
        monthly_growth_max: float | None = None,
        interaction_min: Annotated[float | None, Query(ge=0)] = None,
        interaction_max: Annotated[float | None, Query(ge=0)] = None,
        completion_min: Annotated[float | None, Query(ge=0)] = None,
        completion_max: Annotated[float | None, Query(ge=0)] = None,
        expected_cpm_min: Annotated[float | None, Query(ge=0)] = None,
        expected_cpm_max: Annotated[float | None, Query(ge=0)] = None,
        expected_cpe_min: Annotated[float | None, Query(ge=0)] = None,
        expected_cpe_max: Annotated[float | None, Query(ge=0)] = None,
        cooperation_form: str | None = None,
        complete_only: bool = False,
        sort: Literal[
            "updated_at",
            "followers",
            "monthly_growth",
            "interaction",
            "completion",
            "expected_cpm",
            "expected_cpe",
        ] = "updated_at",
        direction: Literal["asc", "desc"] = "desc",
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> CreatorLibraryPage:
        del user
        ranges = (
            (followers_min, followers_max),
            (monthly_growth_min, monthly_growth_max),
            (interaction_min, interaction_max),
            (completion_min, completion_max),
            (expected_cpm_min, expected_cpm_max),
            (expected_cpe_min, expected_cpe_max),
        )
        if any(low is not None and high is not None and low > high for low, high in ranges):
            raise CollectorError("INVALID_FORM", "INVALID_CREATOR_LIBRARY_RANGE")
        return services.queries.list_creator_library(
            platform=platform,
            creator_scene=creator_scene,
            industry=industry,
            creator_type=creator_type,
            province=province,
            city=city,
            followers_min=followers_min,
            followers_max=followers_max,
            monthly_growth_min=monthly_growth_min,
            monthly_growth_max=monthly_growth_max,
            interaction_min=interaction_min,
            interaction_max=interaction_max,
            completion_min=completion_min,
            completion_max=completion_max,
            expected_cpm_min=expected_cpm_min,
            expected_cpm_max=expected_cpm_max,
            expected_cpe_min=expected_cpe_min,
            expected_cpe_max=expected_cpe_max,
            cooperation_form=cooperation_form,
            complete_only=complete_only,
            sort=sort,
            direction=direction,
            cursor=cursor,
            limit=limit,
        )

    @app.get("/api/creator-library/{creator_id}", response_model=CreatorLibraryDetail)
    def creator_library_detail(
        creator_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE,
    ) -> CreatorLibraryDetail:
        del user
        return services.queries.get_creator_library(creator_id, creator_scene)

    @app.post(
        "/api/creator-library/{creator_id}/updates",
        response_model=CreatorUpdateResponse,
        status_code=202,
    )
    def request_creator_update(
        creator_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> CreatorUpdateResponse:
        updates = services.updates
        if updates is None:
            raise CollectorError("STORAGE_UNAVAILABLE", "UPDATER_NOT_CONFIGURED")
        return updates.create_manual_update(
            creator_id, user_id=user.user_id, idempotency_key=idempotency_key
        )

    @app.get(
        "/api/creator-library/{creator_id}/update",
        response_model=CreatorUpdateStatus,
    )
    def creator_update_status(
        creator_id: str, user: Annotated[AuthenticatedUser, Depends(current_user)]
    ) -> CreatorUpdateStatus:
        del user
        updates = services.updates
        if updates is None:
            raise CollectorError("STORAGE_UNAVAILABLE", "UPDATER_NOT_CONFIGURED")
        return updates.status(creator_id)

    @app.post(
        "/api/creator-library/{creator_id}/live-updates",
        response_model=CreatorUpdateResponse,
        status_code=202,
    )
    def request_creator_live_update(
        creator_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> CreatorUpdateResponse:
        updates = services.live_updates
        if updates is None:
            raise CollectorError("UNSUPPORTED_FILTER", "LIVE_UPDATE_NOT_CONFIGURED")
        return updates.create_manual_update(
            creator_id, user_id=user.user_id, idempotency_key=idempotency_key
        )

    @app.get(
        "/api/creator-library/{creator_id}/live-update",
        response_model=CreatorUpdateStatus,
    )
    def creator_live_update_status(
        creator_id: str, user: Annotated[AuthenticatedUser, Depends(current_user)]
    ) -> CreatorUpdateStatus:
        del user
        updates = services.live_updates
        if updates is None:
            raise CollectorError("UNSUPPORTED_FILTER", "LIVE_UPDATE_NOT_CONFIGURED")
        return updates.status(creator_id)

    @app.get("/api/creator-library/{creator_id}/history", response_model=CreatorLibraryHistory)
    def creator_library_history(
        creator_id: str, user: Annotated[AuthenticatedUser, Depends(current_user)]
    ) -> CreatorLibraryHistory:
        del user
        return services.queries.creator_library_history(creator_id)

    @app.get("/api/creator-library/{creator_id}/quotes", response_model=list[CreatorLibraryQuote])
    def creator_library_quotes(
        creator_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        cooperation_form: str | None = None,
    ) -> list[CreatorLibraryQuote]:
        del user
        return services.queries.creator_library_quotes(creator_id, cooperation_form)

    @app.get("/api/creator-library/{creator_id}/contents")
    def creator_library_contents(
        creator_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        collection_type: Literal["excellent_reach", "excellent_seeding"] = "excellent_reach",
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """精选集合 for the library entry (CD-04); read-only, scoped to the creator's snapshot."""
        del user
        return services.queries.creator_library_contents(
            creator_id, collection_type, cursor=cursor, limit=limit
        )

    @app.get("/api/creator-library/{creator_id}/videos", response_model=CreatorVideoPage)
    def creator_library_videos(
        creator_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        module_key: Literal["recent_video_performance", "recent_xingtu_video_performance"]
        | None = None,
        snapshot_id: str | None = None,
    ) -> CreatorVideoPage:
        """Work observations of one snapshot (DATA-02/CD-08); read-only and creator-scoped."""
        del user
        return services.queries.creator_library_videos(
            creator_id, module_key=module_key, snapshot_id=snapshot_id
        )

    @app.get("/api/creator-library/{creator_id}/covers/{object_id:path}")
    def creator_library_cover(
        creator_id: str,
        object_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
    ) -> Response:
        """A stored cover of **this** creator's collection cards, never another creator's."""
        del user
        try:
            creator_id = str(UUID(creator_id))
        except ValueError as exc:
            raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND") from exc
        reference = services.queries.creator_library_cover_reference(creator_id, object_id)
        if not reference:
            raise CollectorError("INVALID_FORM", "COVER_NOT_FOUND")
        body = services.covers.read(
            object_id,
            checksum=str(reference["checksum"]),
            byte_size=int(reference["byte_size"]),
        )
        return StreamingResponse(iter([body]), media_type=reference["content_type"])

    @app.get(
        "/api/tasks/{root_task_id}/creators/{creator_id}/videos",
        response_model=CreatorVideoPage,
    )
    def creator_videos(
        root_task_id: str,
        creator_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
        module_key: Literal["recent_video_performance", "recent_xingtu_video_performance"]
        | None = None,
        snapshot_id: str | None = None,
    ) -> CreatorVideoPage:
        """The task snapshot's work observations (DATA-02/CD-08); read-only and task-scoped."""
        del user
        return services.queries.task_creator_videos(
            root_task_id, creator_id, module_key=module_key, snapshot_id=snapshot_id
        )

    @app.get("/api/tasks/{root_task_id}/covers/{object_id:path}")
    def cover(
        root_task_id: str,
        object_id: str,
        user: Annotated[AuthenticatedUser, Depends(current_user)],
    ) -> Response:
        del user
        try:
            root_task_id = str(UUID(root_task_id))
        except ValueError as exc:
            raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND") from exc
        reference = services.products.repository.cover_reference(root_task_id, object_id)
        if not reference:
            raise CollectorError("INVALID_FORM", "COVER_NOT_FOUND")
        body = services.covers.read(
            object_id,
            checksum=str(reference["checksum"]),
            byte_size=int(reference["byte_size"]),
        )
        return StreamingResponse(iter([body]), media_type=reference["content_type"])

    return app


def get_application() -> FastAPI:
    return create_app()
