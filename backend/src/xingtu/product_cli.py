from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
from pathlib import Path

import uvicorn

from .contracts import PlatformRegistry
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
    args = parser.parse_args()
    try:
        products = repository() if args.command != "intake-worker" else None
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
        else:
            asyncio.run(_run_intake(args.unit_config, args.profile_requirement))
    except CollectorError as exc:
        raise SystemExit(f"{exc.code}: {exc.reason}") from None


if __name__ == "__main__":
    main()
