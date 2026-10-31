"""KJX-01 stage B: isolated end-to-end product chain for Kuaishou Juxing.

Real FastAPI (TestClient), real PostgreSQL schema, real Temporal test server and the real
``Activities.collect`` activity.  The only synthetic parts are the LLM plan (deterministic) and the
browser boundary (a fake BrowserHost + a synthetic juxing Adapter), so no Chrome, profile, cookie or
platform request is involved.  This is deliberately NOT live-platform acceptance; Windows + a real
Temporal worker on the target machine remain stage C.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from xingtu.contracts import PlatformRegistry
from xingtu.domain import (
    CreatorRef,
    FieldObservation,
    FieldStatus,
    ModuleObservation,
    NumericValue,
    PlatformId,
    ReleaseDisposition,
    SearchPage,
    StructuredValue,
    TaskStatus,
    uid,
)
from xingtu.intake import LLMResult, build_expected_plan
from xingtu.intake_worker import IntakeActivities, IntakeProcessor, dispatch_intakes
from xingtu.intake_workflow import IntakeWorkflow
from xingtu.product_api import ProductServices, ProductSettings, create_app
from xingtu.product_auth import AuthService, MemoryLoginLimiter, PasswordService
from xingtu.product_covers import ProductCoverConfig
from xingtu.product_queries import ProductQueries
from xingtu.product_repository import ProductRepository
from xingtu.repository import Repository
from xingtu.runtime import UnitConfig
from xingtu.worker import Activities, dispatch
from xingtu.workflow import CollectionWorkflow

from backend.tests.synthetic import SyntheticAdapter

ROOT = Path(__file__).resolve().parents[2]
JUXING_REGISTRY_PATH = ROOT / "contracts/kuaishou_juxing.verified.json"
XINGTU_REGISTRY_PATH = ROOT / "contracts/douyin_xingtu.verified.json"
JUXING_ACCOUNT = "60821564"
TEST_USER = "kjx-chain-user"
TEST_PASSWORD = "a-secure-password"


def _juxing_registry() -> PlatformRegistry:
    registry = PlatformRegistry.model_validate_json(JUXING_REGISTRY_PATH.read_text())
    registry.require_enabled(live=True)
    return registry


class CapturingLLM:
    """The plan is derived by the deterministic builder; no paid model call is made here."""

    provider = "synthetic"
    model = "synthetic-flash"

    def __init__(self, registry: PlatformRegistry) -> None:
        self.registry = registry
        self.seen: list[dict[str, Any]] = []

    async def generate_filter_plan(self, **kwargs: Any) -> LLMResult:
        self.seen.append(
            {
                "platform": kwargs["form"].platform,
                "capability_version": kwargs["capabilities"].version,
            }
        )
        plan = build_expected_plan(
            kwargs["form"],
            kwargs["capabilities"],
            capability_version=kwargs["capabilities"].version,
        )
        return LLMResult(payload=plan.model_dump(mode="json"), response_model=self.model)


class SyntheticJuxingAdapter(SyntheticAdapter):
    """Produces one complete observation for every field the verified juxing contract registers."""

    def __init__(self, registry: PlatformRegistry, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.registry = registry
        self.module_keys = [module.key for module in registry.modules]
        self.module_fields = {
            module.key: [field.key for field in module.fields] for module in registry.modules
        }
        self.module_checkpoint_versions = {
            module.key: module.checkpoint_version for module in registry.modules
        }
        self.featured_keys = []
        self.featured_specs = {}
        self.featured_card_fields = {}
        self.featured_checkpoint_versions = {}
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def search(self, plan: Any, cp: Any, ctx: Any):
        """Juxing candidates must carry the juxing platform, exactly like the real adapter."""

        offset = int(cp.cursor or "0")
        ids = self.ids[offset : offset + self.page_size]
        end = offset + self.page_size >= len(self.ids)
        return SearchPage(
            candidates=[
                CreatorRef(
                    platform="kuaishou_juxing",
                    platform_creator_id=value,
                    verified_homepage=f"https://synthetic.invalid/juxing/{value}",
                )
                for value in ids
            ],
            current_checkpoint=cp.cursor,
            next_checkpoint=None if end else str(offset + self.page_size),
            conditions_digest=plan.digest(),
            search_generation=cp.search_generation,
            operation_id=uid(),
            exhausted=end,
            exhaustion_evidence_refs=["synthetic:end"] if end else [],
        )

    async def collect_module(self, key: str, creator: Any, ctx: Any, row_covers: Any = None):
        del row_covers
        module = next(item for item in self.registry.modules if item.key == key)
        operation = uid()
        fields: list[FieldObservation] = []
        for spec in module.fields:
            value: Any
            raw: str
            if spec.key == "platform_creator_id":
                value, raw = creator.platform_creator_id, creator.platform_creator_id
            elif spec.key == "nickname":
                value, raw = "合成聚星达人", "合成聚星达人"
            elif spec.kind == "number":
                amount = "0.01" if spec.unit == "ratio" else "1"
                value, raw = NumericValue(amount=amount), amount
            elif spec.kind == "ratio":
                value, raw = NumericValue(amount="0.01"), "0.01"
            elif spec.kind == "tags":
                value, raw = ["母婴亲子"], '["母婴亲子"]'
            elif spec.kind == "structured":
                value, raw = StructuredValue(data=self._structured(key, spec.key)), "{}"
            else:
                value, raw = f"合成-{spec.key}", f"合成-{spec.key}"
            fields.append(
                FieldObservation(
                    field_key=spec.key,
                    value=value,
                    raw_value=raw,
                    unit=spec.unit,
                    period_label="近30天" if spec.kind in {"number", "ratio"} else None,
                    status=FieldStatus.COLLECTED,
                    source_kind="response",
                    source_contract=self.registry.contract_version,
                    path_ref=f"data.synthetic.{spec.key}",
                    operation_id=operation,
                    session_version=ctx.session_version,
                )
            )
        return ModuleObservation(
            creator_ref=creator,
            module_key=key,
            fields=fields,
            expected_fields=self.module_fields[key],
            operation_id=operation,
            contract_version=ctx.contract_version,
            source_period_label="近30天",
        )

    @staticmethod
    def _structured(module: str, key: str) -> Any:
        if key == "cooperation_offers":
            return [
                {
                    "price_type": 1,
                    "duration": "1-20秒",
                    "platform_price_raw": 20000,
                    "price_yuan": 20,
                    "currency": "CNY",
                }
            ]
        if key == "works":
            return [
                {
                    "platform_content_id": "synthetic-work-1",
                    "title": "合成作品",
                    "play_count": 100,
                    "like_count": 10,
                    "comment_count": 2,
                    "share_count": 1,
                    "published_at_ms": 1760000000000,
                }
            ]
        if module == "audience":
            return {"gender": {"male": 0.4, "female": 0.6}}
        return {"synthetic": True}


class FakeHost:
    """Stand-in for BrowserHost.lease: keeps the real lease/session DB flow, opens no browser."""

    def __init__(
        self,
        repo: Repository,
        config: UnitConfig,
        root_task_id: str,
        owner: str,
        generation: int,
        session_version: int,
        mode: str,
    ) -> None:
        self.repo = repo
        self.config = config
        self.root_task_id = root_task_id
        self.owner = owner
        self.generation = generation
        self.session_version = session_version
        self.mode = mode
        self.browser = object()
        self.browser_instance_id = uid()
        self.session_health = None
        self.release_disposition = ReleaseDisposition.VERIFIED_READY
        self.leases: list[UnitConfig] = []

    @classmethod
    @asynccontextmanager
    async def lease(
        cls,
        repo: Repository,
        config: UnitConfig,
        registry: PlatformRegistry,
        private_root: Path,
        root_task_id: str,
        owner: str,
        *,
        maintenance: bool,
        runtime: Any = None,
    ) -> AsyncIterator[FakeHost]:
        del registry, private_root, runtime
        generation, session_version = repo.acquire(
            config.unit_id, owner, maintenance=maintenance, root_task_id=root_task_id
        )
        host = cls(
            repo,
            config,
            root_task_id,
            owner,
            generation,
            session_version,
            "maintenance" if maintenance else "collect",
        )
        LEASES.append(config)
        try:
            yield host
        finally:
            repo.release(
                config.unit_id,
                owner,
                generation,
                stopped=False,
                disposition=ReleaseDisposition.VERIFIED_READY,
                reason="SYNTHETIC_E2E",
            )

    async def heartbeat(self) -> None:
        return None

    def observe_session(self, health: Any) -> None:
        self.session_health = health

    def take_collection_page(self) -> object:
        return object()

    def enter_maintenance(self, code: str, actor: str) -> None:
        del code, actor


LEASES: list[UnitConfig] = []
FACTORY_CALLS: list[dict[str, Any]] = []


def _factory():
    def build(
        platform: PlatformId,
        browser: Any,
        active_registry: PlatformRegistry,
        expected_account_id: str,
        guard: Any,
        *,
        on_session_health: Any,
        manually_attested_account_id: str | None = None,
    ) -> SyntheticJuxingAdapter:
        del browser, guard, on_session_health, manually_attested_account_id
        FACTORY_CALLS.append(
            {
                "platform": platform,
                "expected_account_id": expected_account_id,
                "contract_version": active_registry.contract_version,
                "adapter_version": active_registry.adapter_version,
                "modules": [module.key for module in active_registry.modules],
            }
        )
        return SyntheticJuxingAdapter(active_registry)

    return build


def _unit_config(tmp_path: Path) -> UnitConfig:
    juxing_profile = tmp_path / "profiles" / "unit-juxing"
    xingtu_profile = tmp_path / "profiles" / "unit-xingtu"
    return UnitConfig.model_validate(
        {
            "unit_id": "unit",
            "account_ref": "synthetic-account",
            "expected_account_id": "synthetic-account",
            "line_id": "synthetic-local",
            "profile_directory": str(xingtu_profile),
            "registry_path": str(XINGTU_REGISTRY_PATH),
            "network_mode": "local_development",
            "browser_channel": "chromium",
            "headless": True,
            "capture_session_snapshot": False,
            "platform_bindings": [
                {
                    "platform": "kuaishou_juxing",
                    "account_ref": "juxing-account",
                    "expected_account_id": JUXING_ACCOUNT,
                    "profile_directory": str(juxing_profile),
                    "registry_path": str(JUXING_REGISTRY_PATH),
                }
            ],
        }
    )


def _services(repo: Repository, *, juxing_enabled: bool = True) -> ProductServices:
    products = ProductRepository(repo)
    passwords = PasswordService()
    products.create_user(TEST_USER, "聚星链路用户", passwords.hash(TEST_PASSWORD), actor="test")
    juxing_registry = _juxing_registry()
    return ProductServices(
        auth=AuthService(products, MemoryLoginLimiter(), passwords=passwords),
        products=products,
        queries=ProductQueries(repo),
        registry=PlatformRegistry.model_validate_json(XINGTU_REGISTRY_PATH.read_text()),
        covers=object(),
        settings=ProductSettings(
            database_url=repo.dsn,
            redis_url="unused",
            login_hmac_key=b"x" * 32,
            registry_path=XINGTU_REGISTRY_PATH,
            juxing_registry_path=JUXING_REGISTRY_PATH,
            enable_kuaishou_juxing=juxing_enabled,
            secure_cookie=True,
            allowed_origins=("https://app.test",),
            cover_config=ProductCoverConfig(
                kind="local", directory=Path(".runtime/covers"), allowed_root=Path(".runtime")
            ),
        ),
        platform_registries={"kuaishou_juxing": juxing_registry},
    )


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": TEST_USER, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


async def _wait_for(predicate: Any, *, timeout: float = 60.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


def _root_state(repo: Repository, root: str) -> str | None:
    """Read the durable state without parsing a pre-promotion intake payload as a task."""

    with repo.connect() as conn:
        row = conn.execute("SELECT state FROM root_tasks WHERE root_task_id=%s", (root,)).fetchone()
    return row["state"] if row else None


def _juxing_form() -> dict[str, Any]:
    return {
        "schema_version": "requirement_form.v3",
        "platform": "kuaishou_juxing",
        "keyword": "母婴",
        "content_types": ["maternal_child"],
        "target_count": 1,
    }


def test_juxing_api_rejects_creation_while_the_flag_is_off(repo):
    client = TestClient(
        create_app(_services(repo, juxing_enabled=False)), base_url="https://app.test"
    )
    csrf = _login(client)
    response = client.post(
        "/api/tasks",
        headers={"Idempotency-Key": uid(), "X-CSRF-Token": csrf, "Origin": "https://app.test"},
        json=_juxing_form(),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "UNSUPPORTED_FILTER"
    assert response.json()["message"] == "KUAISHOU_JUXING_FEATURE_DISABLED"


async def test_juxing_product_chain_from_api_to_temporal_worker_to_library(
    repo: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    registry = _juxing_registry()
    config = _unit_config(tmp_path)
    juxing_binding = config.binding_for(PlatformId.KUAISHOU_JUXING)
    repo.register_unit_platform_binding(
        config.unit_id,
        "kuaishou_juxing",
        juxing_binding.account_ref,
        juxing_binding.expected_account_id,
        str(juxing_binding.profile_directory),
        str(juxing_binding.registry_path),
    )

    monkeypatch.setattr("xingtu.worker.BrowserHost", FakeHost)
    monkeypatch.setattr("xingtu.worker.build_platform_adapter", _factory())
    LEASES.clear()
    FACTORY_CALLS.clear()

    services = _services(repo)
    client = TestClient(create_app(services), base_url="https://app.test")
    csrf = _login(client)
    created = client.post(
        "/api/tasks",
        headers={"Idempotency-Key": uid(), "X-CSRF-Token": csrf, "Origin": "https://app.test"},
        json=_juxing_form(),
    )
    assert created.status_code == 202, created.text
    root = created.json()["root_task_id"]

    # The root task carries the platform from the moment it is accepted.
    with repo.connect() as conn:
        pending = conn.execute(
            "SELECT platform,state FROM root_tasks WHERE root_task_id=%s", (root,)
        ).fetchone()
    assert pending is not None
    assert pending["platform"] == "kuaishou_juxing"
    assert pending["state"] == TaskStatus.RECEIVED.value

    llm = CapturingLLM(registry)
    processor = IntakeProcessor(
        services.products,
        services.registry,
        llm,  # type: ignore[arg-type]
        execution_unit_id="unit",
        profile_requirement=None,
        platform_registries={"kuaishou_juxing": registry},
    )
    activities = Activities(repo, config, tmp_path / "private")
    executable = os.environ.get("XINGTU_TEMPORAL_TEST_BINARY")
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=executable,
        dev_server_download_version="v1.9.1",
        download_dest_dir=str((ROOT / ".runtime/temporal-test").resolve()),
        dev_server_log_level="error",
    ) as env:
        async with (
            Worker(
                env.client,
                task_queue="kjx-intake-test",
                workflows=[IntakeWorkflow],
                activities=[IntakeActivities(processor).process],
            ),
            Worker(
                env.client,
                task_queue="xingtu-unit",
                workflows=[CollectionWorkflow],
                activities=[activities.collect],
            ),
        ):
            dispatched = await dispatch_intakes(
                services.products, env.client, queue="kjx-intake-test"
            )
            assert dispatched == 1
            await _wait_for(lambda: _root_state(repo, root) == TaskStatus.QUEUED.value)
            await dispatch(repo, env.client, queue="xingtu-unit")
            await _wait_for(
                lambda: (
                    _root_state(repo, root)
                    in {
                        TaskStatus.COMPLETED.value,
                        TaskStatus.PARTIAL_COMPLETED.value,
                        TaskStatus.FAILED.value,
                    }
                )
            )

    task = repo.get(root)
    assert task.state == TaskStatus.COMPLETED, task.failure_reason
    assert task.platform == PlatformId.KUAISHOU_JUXING
    assert task.plan is not None and task.plan.platform == "kuaishou_juxing"
    assert task.profile_requirement is None, "Xingtu field inventory must not leak into juxing"
    assert task.valid_count == 1
    assert task.profile_complete_count == 1
    assert task.featured_complete_count == 0

    # The intake graph received exactly the juxing capability contract.
    assert llm.seen == [
        {"platform": "kuaishou_juxing", "capability_version": registry.capabilities.version}
    ]
    # The worker selected the juxing binding/registry/adapter, not the Xingtu defaults.
    assert LEASES and LEASES[0].active_platform == PlatformId.KUAISHOU_JUXING
    assert LEASES[0].expected_account_id == JUXING_ACCOUNT
    assert LEASES[0].registry_path == juxing_binding.registry_path
    assert LEASES[0].profile_directory == juxing_binding.profile_directory
    assert FACTORY_CALLS == [
        {
            "platform": PlatformId.KUAISHOU_JUXING,
            "expected_account_id": JUXING_ACCOUNT,
            "contract_version": registry.contract_version,
            "adapter_version": registry.adapter_version,
            "modules": ["basic", "spread", "works", "audience"],
        }
    ]

    # Data: shared identity/snapshot tables carry juxing; the Xingtu read model stays untouched.
    with repo.connect() as conn:
        identity = conn.execute(
            "SELECT creator_id,platform,platform_creator_id FROM platform_creators"
        ).fetchall()
        assert len(identity) == 1 and identity[0]["platform"] == "kuaishou_juxing"
        creator_id = str(identity[0]["creator_id"])
        snapshots = conn.execute(
            "SELECT payload FROM creator_snapshots WHERE creator_id=%s", (creator_id,)
        ).fetchall()
        assert len(snapshots) == 1
        payload = snapshots[0]["payload"]
        assert set(payload["modules"]) == {"basic", "spread", "works", "audience"}
        assert payload["profile_complete"] is True
        assert payload["pipeline_complete"] is True
        assert (
            conn.execute("SELECT count(*) AS n FROM douyin_xingtu_creator_current").fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT sent FROM task_dispatches WHERE root_task_id=%s", (root,)
            ).fetchone()["sent"]
            is True
        )

    # Product read-back through the same API the UI uses.
    detail = client.get(f"/api/tasks/{root}")
    assert detail.status_code == 200
    assert detail.json()["platform"] == "kuaishou_juxing"
    assert detail.json()["counts"]["valid_count"] == 1
    assert detail.json()["counts"]["featured_complete_count"] == 0

    creators = client.get(f"/api/tasks/{root}/creators")
    assert creators.status_code == 200
    assert len(creators.json()["items"]) == 1
    assert creators.json()["items"][0]["platform"] == "kuaishou_juxing"

    scoped = client.get(f"/api/tasks/{root}/creators/{creator_id}")
    assert scoped.status_code == 200
    assert scoped.json()["payload"]["modules"]["spread"]["status"] == "COLLECTED"

    library = client.get("/api/creator-library?platform=kuaishou_juxing")
    assert library.status_code == 200
    assert [item["creator_id"] for item in library.json()["items"]] == [creator_id]
    assert library.json()["items"][0]["followers"]["value"] == "1"
    assert library.json()["items"][0]["content_theme_labels"] == ["母婴亲子"]

    library_detail = client.get(f"/api/creator-library/{creator_id}")
    assert library_detail.status_code == 200
    body = library_detail.json()
    assert body["platform"] == "kuaishou_juxing"
    assert body["profile_payload"]["modules"]["works"]["status"] == "COLLECTED"
    assert body["module_statuses"]["audience"] == "COLLECTED"

    # Juxing data never appears in the Xingtu library, and juxing-only sub-resources stay explicit.
    xingtu_library = client.get("/api/creator-library?platform=douyin_xingtu")
    assert xingtu_library.json()["items"] == []
    assert client.get(f"/api/creator-library/{creator_id}/quotes").status_code == 422
