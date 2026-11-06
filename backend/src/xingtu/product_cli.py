from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from .contracts import PlatformRegistry
from .creator_update import CreatorUpdateService, UpdateScope, scope_key
from .domain import CollectorError, CreatorScene, PlatformId, ProfileRequirement
from .intake import DeepSeekAdapter
from .intake_worker import IntakeProcessor, run_intake_worker
from .product_auth import PasswordService, normalize_username
from .product_repository import ProductRepository
from .repository import Repository
from .runtime import UnitConfig, load_unit

ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)


def repository() -> ProductRepository:
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        raise CollectorError("STORAGE_UNAVAILABLE", "XINGTU_DATABASE_URL_REQUIRED")
    return ProductRepository(Repository(dsn))


def _new_password() -> str:
    password = getpass.getpass("New product password: ")
    confirmation = getpass.getpass("Confirm product password: ")
    if password != confirmation:
        raise CollectorError("INVALID_FORM", "PASSWORD_CONFIRMATION_MISMATCH")
    return password


def run_api() -> None:
    uvicorn.run(
        "xingtu.product_api:get_application",
        factory=True,
        host=os.environ.get("XINGTU_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("XINGTU_API_PORT", "8000")),
        proxy_headers=False,
    )


def _update_registry(path: Path | None, *, reason: str) -> PlatformRegistry:
    if path is None or not path.is_file():
        raise CollectorError("RESOURCE_UNAVAILABLE", reason)
    try:
        registry = PlatformRegistry.model_validate_json(path.read_text())
        registry.require_enabled(live=True)
    except (OSError, ValidationError) as exc:
        raise CollectorError("RESOURCE_UNAVAILABLE", reason) from exc
    return registry


def _path_or_env(path: Path | None, env_key: str) -> Path | None:
    if path is not None:
        return path
    raw = os.environ.get(env_key)
    return Path(raw) if raw else None


def update_scopes(
    config: UnitConfig, requirement: ProfileRequirement | None
) -> tuple[dict[str, UpdateScope], dict[str, str]]:
    """Resolve every (platform, scene) update lane available to this scheduler process.

    The scheduler is intentionally one process.  A platform's registry may live in the primary
    unit config or in another unit's platform binding; missing optional contracts only disable
    that lane and never stop the others.
    """
    active_platform = config.active_platform
    video_paths: dict[PlatformId, Path | None] = {active_platform: config.registry_path}
    live_paths: dict[PlatformId, Path | None] = {active_platform: config.live_registry_path}
    for binding in config.platform_bindings:
        # A dedicated juxing unit has no top-level live path; its binding still carries one.
        # Prefer every available path without replacing a non-null active-platform value.
        if video_paths.get(binding.platform) is None:
            video_paths[binding.platform] = binding.registry_path
        if live_paths.get(binding.platform) is None:
            live_paths[binding.platform] = binding.live_registry_path
    video_env = {
        "douyin_xingtu": "XINGTU_REGISTRY_PATH",
        "kuaishou_juxing": "XINGTU_JUXING_REGISTRY_PATH",
    }
    live_env = {
        "douyin_xingtu": "XINGTU_LIVE_REGISTRY_PATH",
        "kuaishou_juxing": "XINGTU_JUXING_LIVE_REGISTRY_PATH",
    }
    scopes: dict[str, UpdateScope] = {}
    errors: dict[str, str] = {}
    for platform in (PlatformId.DOUYIN_XINGTU, PlatformId.KUAISHOU_JUXING):
        video_key = scope_key(platform, CreatorScene.VIDEO_SQUARE)
        try:
            video_registry = _update_registry(
                _path_or_env(video_paths.get(platform), video_env[platform.value]),
                reason="UPDATE_VIDEO_REGISTRY_UNAVAILABLE",
            )
        except CollectorError as exc:
            errors[video_key] = exc.reason
        else:
            scopes[video_key] = UpdateScope(
                platform,
                CreatorScene.VIDEO_SQUARE,
                video_registry,
                requirement if platform == PlatformId.DOUYIN_XINGTU else None,
            )
        live_key = scope_key(platform, CreatorScene.LIVE_SQUARE)
        try:
            live_registry = _update_registry(
                _path_or_env(live_paths.get(platform), live_env[platform.value]),
                reason="UPDATE_LIVE_REGISTRY_UNAVAILABLE",
            )
        except CollectorError as exc:
            errors[live_key] = exc.reason
        else:
            scopes[live_key] = UpdateScope(platform, CreatorScene.LIVE_SQUARE, live_registry)
    return scopes, errors


async def _run_update_scheduler(
    unit_config: Path,
    profile_requirement_path: Path | None,
    *,
    batch_size: int,
    tick_seconds: float,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = load_unit(unit_config)
    requirement = (
        ProfileRequirement.model_validate_json(profile_requirement_path.read_text())
        if profile_requirement_path
        else None
    )
    scopes, scope_errors = update_scopes(config, requirement)
    primary = scope_key(config.active_platform, CreatorScene.VIDEO_SQUARE)
    if primary not in scopes:
        raise CollectorError(
            "RESOURCE_UNAVAILABLE",
            scope_errors.get(primary) or "UPDATE_PRIMARY_SCOPE_UNAVAILABLE",
        )
    for key, reason in scope_errors.items():
        logger.warning("creator update scope unavailable scope=%s reason=%s", key, reason)
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        raise CollectorError("STORAGE_UNAVAILABLE", "XINGTU_DATABASE_URL_REQUIRED")
    service = CreatorUpdateService(
        Repository(dsn),
        scopes=scopes,
        scope_errors=scope_errors,
        batch_size=batch_size,
        tick_seconds=tick_seconds,
    )
    while True:
        try:
            result = service.scheduler_tick()
            if result["created"] or result["errors"]:
                logger.info(
                    "creator update tick created=%s reconciled=%s enrolled=%s skipped=%s "
                    "groups=%s errors=%s",
                    result["created"],
                    result["reconciled"],
                    result["enrolled"],
                    result["skipped"],
                    result["groups"],
                    result["errors"],
                )
        except Exception as exc:  # noqa: BLE001 - the scheduler must survive any tick error
            logger.warning("creator update scheduler tick failed: %s", type(exc).__name__)
        await asyncio.sleep(tick_seconds)


async def _run_intake(unit_config: Path, profile_requirement: Path | None) -> None:
    # Worker lifecycle and dispatch failures must be visible in the process log; without this the
    # consumer could die silently and look identical to "no worker is running".
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = load_unit(unit_config)
    registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
    registry.require_enabled(live=True)
    platform_registries: dict[str, PlatformRegistry] = {}
    for binding in config.platform_bindings:
        # `enabled` gates whether THIS unit may execute a platform task; it does not make the
        # platform contract untranslatable. A dedicated Xingtu unit keeps the Juxing contract
        # declared (enabled=false) so the intake worker can still convert a Juxing requirement
        # before the dedicated Juxing collection unit executes it.
        try:
            bound_registry = PlatformRegistry.model_validate_json(binding.registry_path.read_text())
            bound_registry.require_enabled(live=True)
        except (OSError, ValidationError) as exc:
            if binding.enabled:
                raise
            logger.warning(
                "disabled platform registry unavailable: %s (%s)",
                binding.platform.value,
                type(exc).__name__,
            )
            continue
        platform_registries[binding.platform.value] = bound_registry
    scene_registries: dict[str, PlatformRegistry] = {}
    live_paths: list[tuple[str, Path]] = []
    if config.live_registry_path:
        live_paths.append((config.active_platform.value, config.live_registry_path))
    for binding in config.platform_bindings:
        if binding.live_registry_path:
            live_paths.append((binding.platform.value, binding.live_registry_path))
    # The intake worker has one unit config; a platform's dedicated worker config may be a
    # different file.  The environment paths are the explicit cross-platform source for P1.
    for platform, env_key in (
        ("douyin_xingtu", "XINGTU_LIVE_REGISTRY_PATH"),
        ("kuaishou_juxing", "XINGTU_JUXING_LIVE_REGISTRY_PATH"),
    ):
        raw = os.environ.get(env_key)
        if raw:
            live_paths.append((platform, Path(raw)))
    for platform, live_path in live_paths:
        try:
            live_registry = PlatformRegistry.model_validate_json(live_path.read_text())
            live_registry.require_enabled(live=True)
        except (OSError, ValidationError) as exc:
            logger.warning("live registry unavailable: %s (%s)", platform, type(exc).__name__)
            continue
        scene_registries[f"{platform}:live_square"] = live_registry
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise CollectorError("RESOURCE_UNAVAILABLE", "DEEPSEEK_API_KEY_REQUIRED")
    requirement = (
        ProfileRequirement.model_validate_json(profile_requirement.read_text())
        if profile_requirement
        else None
    )
    adapter = DeepSeekAdapter(
        api_key,
        model=os.environ.get("XINGTU_DEEPSEEK_MODEL", "deepseek-flash"),
        base_url=os.environ.get("XINGTU_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    await adapter.verify_model()
    products = repository()
    processor = IntakeProcessor(
        products,
        registry,
        adapter,
        execution_unit_id=config.unit_id,
        profile_requirement=requirement,
        platform_registries=platform_registries,
        scene_registries=scene_registries,
    )
    await run_intake_worker(
        products,
        processor,
        os.environ.get("XINGTU_TEMPORAL_ADDRESS", "127.0.0.1:57233"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="M3 product administration and intake worker")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--actor", required=True)
    state = commands.add_parser("set-user-active")
    state.add_argument("--username", required=True)
    state.add_argument("--active", choices=["yes", "no"], required=True)
    state.add_argument("--actor", required=True)
    reset = commands.add_parser("reset-password")
    reset.add_argument("--username", required=True)
    reset.add_argument("--actor", required=True)
    intake = commands.add_parser("intake-worker")
    intake.add_argument("--unit-config", type=Path, required=True)
    intake.add_argument(
        "--profile-requirement",
        type=Path,
        default=ROOT / "contracts/profile_requirements.json",
    )
    scheduler = commands.add_parser("update-scheduler")
    scheduler.add_argument("--unit-config", type=Path, required=True)
    scheduler.add_argument(
        "--profile-requirement",
        type=Path,
        default=ROOT / "contracts/profile_requirements.json",
    )
    scheduler.add_argument("--batch-size", type=int, default=5)
    scheduler.add_argument("--tick-seconds", type=float, default=60.0)
    args = parser.parse_args()
    try:
        products = (
            repository() if args.command not in {"intake-worker", "update-scheduler"} else None
        )
        if args.command == "create-user":
            assert products
            username = normalize_username(args.username)
            user_id = products.create_user(
                username,
                args.display_name.strip(),
                PasswordService().hash(_new_password()),
                actor=args.actor,
            )
            print(user_id)
        elif args.command == "set-user-active":
            assert products
            user_id = products.set_user_active(
                normalize_username(args.username), args.active == "yes", actor=args.actor
            )
            print(user_id)
        elif args.command == "reset-password":
            assert products
            user_id = products.reset_password(
                normalize_username(args.username),
                PasswordService().hash(_new_password()),
                actor=args.actor,
            )
            print(user_id)
        elif args.command == "update-scheduler":
            asyncio.run(
                _run_update_scheduler(
                    args.unit_config,
                    args.profile_requirement,
                    batch_size=args.batch_size,
                    tick_seconds=args.tick_seconds,
                )
            )
        else:
            asyncio.run(_run_intake(args.unit_config, args.profile_requirement))
    except CollectorError as exc:
        raise SystemExit(f"{exc.code}: {exc.reason}") from None


if __name__ == "__main__":
    main()
