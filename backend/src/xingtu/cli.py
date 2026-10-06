from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from temporalio.client import Client

from .browser_host import wait_for_manual_clearance
from .contracts import PlatformRegistry
from .covers import CoverPipeline, build_cover_store
from .diagnostics import run_session_diagnostics
from .domain import CollectorError, FilterPlan, NetworkMode, ProfileRequirement, SegmentBudget
from .evidence import EvidenceConfig
from .repository import Repository
from .research import ResearchStep, run_research
from .runtime import (
    browser_compatibility_report,
    confirm_local_browser_stopped,
    ensure_line,
    load_unit,
)
from .worker import dispatch, run_worker

ROOT = Path(__file__).resolve().parents[3]


def repository() -> Repository:
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        raise CollectorError("STORAGE_UNAVAILABLE", "XINGTU_DATABASE_URL_REQUIRED")
    return Repository(dsn)


def login_timeout_default() -> float:
    return 900.0


async def wait_for_manual_login(page: Any, spec: Any, timeout: float) -> str:
    """Compatibility wrapper for contract tests; production ownership lives in BrowserHost."""
    return await wait_for_manual_clearance(page, spec, timeout)


async def login(path: Path, wait_seconds: float) -> None:
    config = load_unit(path)
    repo = repository()
    resumed = repo.request_login_maintenance(config.unit_id, "login-cli")
    if not resumed:
        raise CollectorError("INVALID_FORM", "NO_WAITING_LOGIN_TASK")
    client = await Client.connect(os.environ.get("XINGTU_TEMPORAL_ADDRESS", "127.0.0.1:57233"))
    await dispatch(repo, client, f"xingtu-{config.unit_id}")
    print(
        f"已向 {resumed} 个原等待任务发送幂等维护请求。"
        f"Worker 将打开有界 Chrome（最长 {int(wait_seconds)} 秒）；"
        "请只在该 Chrome 内使用平台正常短信或账号密码登录，不要在聊天中发送任何凭据。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="F04/F05 内部验收工具，不绕过产品 P1 提交契约")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--environment", choices=["development", "test"], required=True)
    recover = commands.add_parser("recover-unit")
    recover.add_argument("--config", type=Path, required=True)
    recover.add_argument("--actor", required=True)
    enable = commands.add_parser("enable-contract")
    enable.add_argument("--registry", type=Path, required=True)
    enable.add_argument("--actor", required=True)
    enable.add_argument("--scope")
    enable.add_argument("--reason")
    register = commands.add_parser("register-unit")
    register.add_argument("--config", type=Path, required=True)
    rebind = commands.add_parser("rebind-account")
    rebind.add_argument("--config", type=Path, required=True)
    rebind.add_argument("--account-id", required=True)
    rebind.add_argument("--actor", required=True)
    rebind.add_argument("--reason", required=True)
    rebind.add_argument("--evidence-ref")
    rebind.add_argument(
        "--previous-account-id",
        help="被取代的旧绑定（仅当旧绑定只存在于单元配置文件、未落库时使用）",
    )
    login_command = commands.add_parser("login")
    login_command.add_argument("--config", type=Path, required=True)
    login_command.add_argument("--wait-seconds", type=float, default=login_timeout_default())
    worker_command = commands.add_parser("worker")
    worker_command.add_argument("--config", type=Path, required=True)
    browser_check = commands.add_parser("browser-check")
    browser_check.add_argument("--config", type=Path, required=True)
    session_diagnostics = commands.add_parser("session-diagnostics")
    session_diagnostics.add_argument("--config", type=Path, required=True)
    session_diagnostics.add_argument(
        "--out", type=Path, default=ROOT / ".runtime/session-diagnostics"
    )
    preflight = commands.add_parser("production-preflight")
    preflight.add_argument("--config", type=Path, required=True)
    cover_gc = commands.add_parser("cover-gc")
    cover_gc.add_argument("--config", type=Path, required=True)
    research = commands.add_parser("research")
    research.add_argument("--config", type=Path, required=True)
    research.add_argument("--url", required=True)
    research.add_argument("--out", type=Path, required=True)
    research.add_argument("--steps", type=Path)
    research.add_argument("--login-wait-seconds", type=float, default=0.0)
    research.add_argument("--login-done-file", type=Path)
    research.add_argument("--screenshots", action="store_true")
    research.add_argument("--capture-status-message", action="store_true")
    research.add_argument("--bind-check", action="store_true")
    start = commands.add_parser("start")
    start.add_argument("--plan", type=Path, required=True)
    start.add_argument("--config", type=Path, required=True)
    start.add_argument("--key", required=True)
    start.add_argument("--actor", required=True)
    start.add_argument(
        "--requirements", type=Path, default=ROOT / "contracts/profile_requirements.json"
    )
    for name in ("status", "results"):
        command = commands.add_parser(name)
        command.add_argument("root_task_id")
    for name in ("cancel", "continue", "retry"):
        command = commands.add_parser(name)
        command.add_argument("root_task_id")
        command.add_argument("--version", type=int, required=True)
        command.add_argument("--actor", required=True)
    dispatch_parser = commands.add_parser("dispatch")
    dispatch_parser.add_argument("--unit", required=True)
    args = parser.parse_args()
    try:
        address = os.environ.get("XINGTU_TEMPORAL_ADDRESS", "127.0.0.1:57233")
        if args.command == "doctor":
            registry = PlatformRegistry.model_validate_json(
                (ROOT / "contracts/douyin_xingtu.unverified.json").read_text()
            )
            print(
                json.dumps(
                    {
                        "live_status": registry.status,
                        "coverage_gaps": registry.coverage_gaps,
                        "database_configured": bool(os.environ.get("XINGTU_DATABASE_URL")),
                        "segment_budget": SegmentBudget().model_dump(mode="json"),
                        "evidence_default": EvidenceConfig().model_dump(mode="json"),
                        "featured_collections": [spec.key.value for spec in registry.featured],
                        "featured_status": "NOT_ATTEMPTED"
                        if not registry.featured
                        else "REGISTERED",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "migrate":
            repository().migrate(ROOT / "migrations")
            print("all pending migrations applied or already present")
        elif args.command == "recover-unit":
            config = load_unit(args.config)
            confirm_local_browser_stopped(config, ROOT / ".runtime/profiles")
            repository().recover_stopped_unit(config.unit_id, args.actor)
            print("unit isolated; current session must be re-observed before collection")
        elif args.command == "enable-contract":
            registry = PlatformRegistry.model_validate_json(args.registry.read_text())
            registry.require_enabled(live=True)
            if args.scope:
                repository().enable_contract_scope(
                    registry.contract_version,
                    args.scope,
                    args.actor,
                    args.reason or "",
                )
                print("verified contract scope enabled")
            else:
                if args.reason:
                    raise CollectorError("INVALID_FORM", "SCOPE_REQUIRED_FOR_REASON")
                repository().enable_contract(registry.contract_version, args.actor)
                print("verified global contract override enabled")
        elif args.command == "register-unit":
            config = load_unit(args.config)
            repository().register_unit(
                config.unit_id,
                config.account_ref,
                config.line_id,
                str(config.profile_directory.resolve()),
                config.network_mode.value,
                config.expected_account_id,
            )
            print(
                json.dumps(
                    {
                        "unit_id": config.unit_id,
                        "state": "NEEDS_LOGIN",
                        "network_mode": config.network_mode.value,
                    }
                )
            )
        elif args.command == "rebind-account":
            # Explicit, audited account rebinding: never automatic, never while a browser owns
            # the unit.  The config file must already carry the same identity.
            config = load_unit(args.config)
            if config.expected_account_id != args.account_id:
                raise CollectorError("INVALID_FORM", "UNIT_CONFIG_ACCOUNT_MUST_MATCH_REBIND_TARGET")
            previous = repository().rebind_unit_account(
                config.unit_id,
                args.account_id,
                args.actor,
                args.reason,
                args.evidence_ref,
                args.previous_account_id,
            )
            print(
                json.dumps(
                    {
                        "unit_id": config.unit_id,
                        "previous_account_id": previous,
                        "expected_account_id": args.account_id,
                        "state": "SESSION_UNVERIFIED",
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "login":
            asyncio.run(login(args.config, args.wait_seconds))
        elif args.command == "browser-check":
            config = load_unit(args.config)
            report = asyncio.run(browser_compatibility_report(config, ROOT / ".runtime/profiles"))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "session-diagnostics":
            config = load_unit(args.config)
            path = asyncio.run(
                run_session_diagnostics(
                    config,
                    ROOT / ".runtime/profiles",
                    args.out,
                )
            )
            print(json.dumps({"report": str(path), "contains_plaintext_tokens": False}))
        elif args.command == "production-preflight":
            # Explicit production entry: a local-development unit must never pass this gate.
            config = load_unit(args.config)
            if config.network_mode != NetworkMode.PRODUCTION_LINE:
                raise CollectorError(
                    "RESOURCE_UNAVAILABLE", "LOCAL_DEVELOPMENT_UNIT_IS_NOT_A_PRODUCTION_LINE"
                )
            registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
            registry.require_enabled(live=True)
            asyncio.run(ensure_line(config))
            print(
                json.dumps(
                    {
                        "network_mode": config.network_mode.value,
                        "line_id": config.line_id,
                        "probe": "verified",
                        "contract": registry.contract_version,
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "cover-gc":
            config = load_unit(args.config)
            pipeline = CoverPipeline(
                repository(),
                build_cover_store(config.covers, repository(), ROOT / ".runtime"),
            )
            removed = pipeline.cleanup_unreferenced()
            print(json.dumps({"removed": removed, "count": len(removed)}, ensure_ascii=False))
        elif args.command == "research":
            config = load_unit(args.config)
            steps = (
                [ResearchStep.model_validate(item) for item in json.loads(args.steps.read_text())]
                if args.steps
                else []
            )
            report = asyncio.run(
                run_research(
                    config,
                    ROOT / ".runtime",
                    start_url=args.url,
                    out_dir=args.out,
                    steps=steps,
                    login_wait_seconds=args.login_wait_seconds,
                    screenshots=args.screenshots,
                    login_done_file=args.login_done_file,
                    capture_status_message=args.capture_status_message,
                    bind_check=args.bind_check,
                )
            )
            print(
                json.dumps(
                    {
                        "out": str(args.out),
                        "snapshots": len(report["snapshots"]),
                        "browser_version": report.get("browser_version"),
                        "browser_stopped": report.get("browser_stopped"),
                        "network_mode": report["network_mode"],
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "worker":
            config = load_unit(args.config)
            asyncio.run(run_worker(repository(), config, address, ROOT / ".runtime/profiles"))
        elif args.command == "start":
            config = load_unit(args.config)
            registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
            registry.require_enabled(live=True)
            required_scopes = {"session", "search", "profile_identity"}
            required_scopes.update(f"profile_module:{item.key}" for item in registry.modules)
            required_scopes.update(f"featured:{item.key.value}" for item in registry.featured)
            repository().require_contract(registry.contract_version, required_scopes)
            plan = FilterPlan.model_validate_json(args.plan.read_text())
            registry.capabilities.validate_plan(plan, live=True)
            root = repository().create(
                plan,
                config.unit_id,
                args.key,
                args.actor,
                adapter_version=registry.adapter_version,
                contract_version=registry.contract_version,
                modules=[m.key for m in registry.modules],
                profile_requirement=ProfileRequirement.model_validate_json(
                    args.requirements.read_text()
                ),
                module_checkpoint_versions={m.key: m.checkpoint_version for m in registry.modules},
                featured_types=[spec.key.value for spec in registry.featured],
                featured_checkpoint_versions={
                    spec.key.value: spec.checkpoint_version for spec in registry.featured
                },
            )
            print(json.dumps({"root_task_id": root, "source": "internal_acceptance"}))
        elif args.command == "status":
            task = repository().get(args.root_task_id)
            data = task.model_dump(mode="json", exclude={"checkpoint", "plan"})
            checkpoint = task.checkpoint
            data["discovered_count"] = len(checkpoint.candidates)
            data["scanned_count_segment"] = len(checkpoint.scanned_ids)
            data["search_generation"] = checkpoint.search_generation
            data["search_exhausted"] = checkpoint.exhausted
            data["search_stop_reason"] = checkpoint.search_stop_reason
            data["active_seconds"] = checkpoint.active_seconds
            data["runtime_metrics"] = {
                "observed_requests": checkpoint.observed_requests,
                "observed_responses": checkpoint.observed_responses,
                "module_seconds": checkpoint.module_seconds,
                "failure_counts": checkpoint.failure_counts,
                "request_scope": "registered_operation_matches_only",
            }
            data["exhaustion_evidence_refs"] = checkpoint.exhaustion_evidence_refs
            data["rescan_reasons"] = checkpoint.rescan_reasons
            data["unidentified_rows"] = [d.model_dump(mode="json") for d in checkpoint.diagnostics]
            data["profile_checkpoint_versions"] = checkpoint.profile_checkpoint_versions
            data["featured_checkpoint_versions"] = checkpoint.featured_checkpoint_versions
            data["draft_results"] = [
                {
                    "creator_id": c.ref.creator_id,
                    "platform_creator_id": c.ref.platform_creator_id,
                    "valid": c.valid,
                    "state": c.state,
                    "failure_reason": c.failure_reason,
                    "profile_coverage": Repository.profile_coverage(
                        task, c.ref.platform_creator_id
                    ),
                    "modules": {
                        k: {
                            "status": m.status,
                            "complete": m.complete,
                            "coverage_gaps": m.coverage_gaps,
                            "fields": {
                                f.field_key: {
                                    "status": f.status,
                                    "failure_reason": f.failure_reason,
                                }
                                for f in m.fields
                            },
                        }
                        for k, m in c.modules.items()
                    },
                    "collections": {
                        k: {
                            "status": o.status,
                            "complete": o.complete,
                            "card_count": len(o.cards),
                            "observed_at": o.observed_at,
                            "coverage_gaps": o.coverage_gaps,
                            "coverage_notes": o.coverage_notes,
                            "covers": {
                                card.card_id: card.cover.status if card.cover else "NOT_ATTEMPTED"
                                for card in o.cards
                            },
                        }
                        for k, o in c.collections.items()
                    },
                }
                for c in checkpoint.candidates
            ]
            print(json.dumps(data, ensure_ascii=False, indent=2))
        elif args.command == "results":
            print(
                json.dumps(
                    repository().results(args.root_task_id),
                    default=str,
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command in {"cancel", "continue", "retry"}:
            repository().command(args.root_task_id, args.command, args.version, args.actor)
            print("accepted")
        elif args.command == "dispatch":

            async def run_dispatch() -> None:
                client = await Client.connect(address)
                await dispatch(repository(), client, f"xingtu-{args.unit}")

            asyncio.run(run_dispatch())
    except CollectorError as exc:
        print(json.dumps({"error_code": exc.code, "reason": exc.reason}), file=sys.stderr)
        raise SystemExit(2) from None
    except ValidationError:
        # Input/config validation errors can include secrets; do not echo Pydantic input values.
        print("INVALID_CONFIG_OR_SCHEMA: review the referenced local input", file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
        # A missing/unreadable local input must fail with a stable code, not a traceback.
        print(
            json.dumps(
                {
                    "error_code": "INVALID_FORM",
                    "reason": "INPUT_FILE_UNREADABLE",
                    "path": getattr(exc, "filename", None),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
