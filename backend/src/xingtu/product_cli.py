from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
from pathlib import Path

import uvicorn

from .contracts import PlatformRegistry
from .creator_update import CreatorUpdateService
from .domain import CollectorError, ProfileRequirement
from .intake import DeepSeekAdapter
from .intake_worker import IntakeProcessor, run_intake_worker
from .product_auth import PasswordService, normalize_username
from .product_repository import ProductRepository
from .repository import Repository
from .runtime import load_unit

ROOT = Path(__file__).resolve().parents[3]


def repository() -> ProductRepository:
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        raise CollectorError("STORAGE_UNAVAILABLE", "XINGTU_DATABASE_URL_REQUIRED")
    return ProductRepository(Repository(dsn))


def resolve_intake_config(
    unit_config: Path | None,
    execution_unit_id: str | None,
    registry_path: Path,
) -> tuple[str, Path]:
    """Resolve the old Mac-local config or the decoupled cloud control-plane inputs."""
    if unit_config:
        unit = load_unit(unit_config)
        return execution_unit_id or unit.unit_id, unit.registry_path
    resolved_unit_id = execution_unit_id or os.environ.get("XINGTU_DEFAULT_EXECUTION_UNIT_ID", "")
    if not resolved_unit_id:
        raise CollectorError("RESOURCE_UNAVAILABLE", "DEFAULT_EXECUTION_UNIT_ID_REQUIRED")
    return resolved_unit_id, registry_path


def _new_password() -> str:
    password = getpass.getpass("New product password: ")
    confirmation = getpass.getpass("Confirm product password: ")
    if password != confirmation:
        raise CollectorError("INVALID_FORM", "PASSWORD_CONFIRMATION_MISMATCH")
    return password


def run_api() -> None:
    forwarded_allow_ips = os.environ.get("XINGTU_FORWARDED_ALLOW_IPS", "127.0.0.1")
    uvicorn.run(
        "xingtu.product_api:get_application",
        factory=True,
        host=os.environ.get("XINGTU_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("XINGTU_API_PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips,
    )


async def _run_update_scheduler(
    registry_path: Path,
    profile_requirement_path: Path | None,
    *,
    batch_size: int,
    tick_seconds: float,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    registry = PlatformRegistry.model_validate_json(registry_path.read_text())
    registry.require_enabled(live=True)
    requirement = (
        ProfileRequirement.model_validate_json(profile_requirement_path.read_text())
        if profile_requirement_path
        else None
    )
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        raise CollectorError("STORAGE_UNAVAILABLE", "XINGTU_DATABASE_URL_REQUIRED")
    service = CreatorUpdateService(Repository(dsn), registry, requirement, batch_size=batch_size)
    while True:
        try:
            result = service.scheduler_tick()
            if result["created"]:
                logging.getLogger(__name__).info(
                    "creator update batch created=%s reconciled=%s enrolled=%s",
                    result["created"],
                    result["reconciled"],
                    result["enrolled"],
                )
        except Exception as exc:  # noqa: BLE001 - the scheduler must survive any tick error
            logging.getLogger(__name__).warning(
                "creator update scheduler tick failed: %s", type(exc).__name__
            )
        await asyncio.sleep(tick_seconds)


async def _run_intake(
    execution_unit_id: str,
    registry_path: Path,
    profile_requirement: Path | None,
) -> None:
    # Worker lifecycle and dispatch failures must be visible in the process log; without this the
    # consumer could die silently and look identical to "no worker is running".
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    registry = PlatformRegistry.model_validate_json(registry_path.read_text())
    registry.require_enabled(live=True)
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
        execution_unit_id=execution_unit_id,
        profile_requirement=requirement,
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
    intake.add_argument("--unit-config", type=Path)
    intake.add_argument("--execution-unit-id")
    intake.add_argument(
        "--registry",
        type=Path,
        default=Path(
            os.environ.get("XINGTU_REGISTRY_PATH", ROOT / "contracts/douyin_xingtu.verified.json")
        ),
    )
    intake.add_argument(
        "--profile-requirement",
        type=Path,
        default=ROOT / "contracts/profile_requirements.json",
    )
    scheduler = commands.add_parser("update-scheduler")
    scheduler.add_argument("--unit-config", type=Path)
    scheduler.add_argument(
        "--registry",
        type=Path,
        default=Path(
            os.environ.get("XINGTU_REGISTRY_PATH", ROOT / "contracts/douyin_xingtu.verified.json")
        ),
    )
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
            registry_path = (
                load_unit(args.unit_config).registry_path if args.unit_config else args.registry
            )
            asyncio.run(
                _run_update_scheduler(
                    registry_path,
                    args.profile_requirement,
                    batch_size=args.batch_size,
                    tick_seconds=args.tick_seconds,
                )
            )
        else:
            execution_unit_id, registry_path = resolve_intake_config(
                args.unit_config, args.execution_unit_id, args.registry
            )
            asyncio.run(_run_intake(execution_unit_id, registry_path, args.profile_requirement))
    except CollectorError as exc:
        raise SystemExit(f"{exc.code}: {exc.reason}") from None


if __name__ == "__main__":
    main()
