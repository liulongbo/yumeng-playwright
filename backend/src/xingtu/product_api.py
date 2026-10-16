import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import Cookie, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from redis import Redis
from starlette.middleware.base import RequestResponseEndpoint

from .contracts import PlatformRegistry
from .domain import CollectorError, TaskStatus
from .product_auth import AuthService, RedisLoginLimiter
from .product_covers import ProductCoverConfig, ProductCoverReader
from .product_models import (
    AuthenticatedUser,
    CommandRequest,
    CreateTaskResponse,
    CreatorLibraryDetail,
    CreatorLibraryHistory,
    CreatorLibraryPage,
    CreatorLibraryQuote,
    CreatorPage,
    CreatorSummary,
    FieldError,
    LoginRequest,
    ProductError,
    ProfileFieldCatalog,
    RequirementForm,
    TaskDetail,
    TaskPage,
    UserView,
)
from .product_queries import ProductQueries
from .product_repository import ProductRepository
from .profile_catalog import build_profile_field_catalog
from .repository import Repository
from .worker_health import INTAKE_QUEUE, WorkerHealthMonitor

SESSION_COOKIE = "xingtu_product_session"
CSRF_HEADER = "X-CSRF-Token"


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
        )


@dataclass
class ProductServices:
    auth: AuthService
    products: ProductRepository
    queries: ProductQueries
    registry: PlatformRegistry
    covers: ProductCoverReader
    settings: ProductSettings


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
    return ProductServices(
        auth=auth,
        products=products,
        queries=ProductQueries(repository, worker_health),
        registry=registry,
        covers=ProductCoverReader(settings.cover_config or ProductCoverConfig()),
        settings=settings,
    )


def _status_for_error(exc: CollectorError) -> int:
    if exc.code == "ACCOUNT_LOGIN_REQUIRED":
        return 401
    if exc.reason in {"CSRF_CHECK_FAILED", "ORIGIN_CHECK_FAILED"}:
        return 403
    if exc.reason in {"TASK_NOT_FOUND", "CREATOR_NOT_FOUND", "COVER_NOT_FOUND"}:
        return 404
    if exc.reason in {
        "IDEMPOTENCY_CONFLICT",
        "STATE_VERSION_CONFLICT",
        "ACTION_NOT_ALLOWED",
        "NO_RETRYABLE_FAILURE",
        "INTAKE_STATE_CONFLICT",
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

    @app.get("/api/platforms/douyin_xingtu/capabilities")
    def capabilities(user: Annotated[AuthenticatedUser, Depends(current_user)]) -> dict[str, Any]:
        del user
        from .product_models import CapabilityDTO

        return CapabilityDTO.from_capabilities(services.registry.capabilities).model_dump(
            mode="json"
        )

    @app.get(
        "/api/platforms/douyin_xingtu/profile-field-catalog",
        response_model=ProfileFieldCatalog,
    )
    def profile_field_catalog(
        user: Annotated[AuthenticatedUser, Depends(current_user)],
    ) -> ProfileFieldCatalog:
        """Display names, kinds and registered units for the 81 profile fields.

        Read-only projection of the already-loaded verified registry: no database access, no
        business values.  Evidence-corrected display names are marked with `name_source`.
        """

        del user
        return build_profile_field_catalog(services.registry)

    @app.post("/api/tasks", response_model=CreateTaskResponse, status_code=202)
    def create_task(
        form: RequirementForm,
        user: Annotated[AuthenticatedUser, Depends(current_user_with_csrf)],
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
        origin_root_task_id: Annotated[UUID | None, Header(alias="X-Origin-Root-Task-Id")] = None,
    ) -> CreateTaskResponse:
        return services.products.create_product_task(
            form,
            capability_version=services.registry.capabilities.version,
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
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> TaskPage:
        del user
        return services.queries.list_tasks(
            status=status,
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
        platform: Literal["douyin_xingtu"] = "douyin_xingtu",
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
        del user, platform
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
        creator_id: str, user: Annotated[AuthenticatedUser, Depends(current_user)]
    ) -> CreatorLibraryDetail:
        del user
        return services.queries.get_creator_library(creator_id)

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
