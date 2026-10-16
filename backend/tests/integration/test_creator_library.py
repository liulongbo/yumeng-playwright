from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from xingtu.contracts import PlatformRegistry
from xingtu.creator_library import CreatorLibraryWriter
from xingtu.domain import uid
from xingtu.product_api import ProductServices, ProductSettings, create_app
from xingtu.product_auth import AuthService, MemoryLoginLimiter, PasswordService
from xingtu.product_covers import ProductCoverConfig
from xingtu.product_queries import ProductQueries
from xingtu.product_repository import ProductRepository


def _seed_creator_library(repo, plan):
    root = repo.create(
        plan,
        "unit",
        "creator-library-seed",
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    creator_id = uid()
    snapshot_id = uid()
    captured_at = datetime(2026, 10, 12, 8, 9, tzinfo=UTC)
    sources = {
        "followers_count": {
            "status": "COLLECTED",
            "unit": "count",
            "observed_at": captured_at.isoformat(),
            "source_contract": "test-v1",
        },
        "monthly_deep_users_count": {
            "status": "COLLECTED",
            "unit": "count",
            "observed_at": captured_at.isoformat(),
        },
    }
    with repo.connect() as conn:
        conn.execute(
            "INSERT INTO platform_creators(creator_id,platform,platform_creator_id) "
            "VALUES(%s,%s,%s)",
            (creator_id, "douyin_xingtu", "creator-library-sample"),
        )
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,created_at)
            VALUES(%s,%s,%s,1,%s,%s)""",
            (
                snapshot_id,
                root,
                creator_id,
                Jsonb({"modules": {}, "profile_complete": True, "pipeline_complete": True}),
                captured_at,
            ),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_current(
            creator_id,platform_creator_id,latest_snapshot_id,display_name,creator_type_label,province,city,
            industry_labels,followers_count,followers_raw,monthly_deep_users_count,monthly_deep_users_raw,
            monthly_deep_users_is_approximate,interaction_rate_value_raw,completion_rate_value_raw,
            expected_cpm_21_60_raw,expected_cpe_21_60_raw,profile_complete,pipeline_complete,
            collected_field_count,failed_field_count,field_sources,data_updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,true,true,80,0,%s,%s)""",
            (
                creator_id,
                "creator-library-sample",
                snapshot_id,
                "达人 A",
                "生活",
                "北京市",
                "朝阳区",
                Jsonb(["食品饮料", "汽车"]),
                5704674,
                "5704674",
                48899000,
                "4,889.9w",
                428,
                6343,
                10029,
                934,
                Jsonb(sources),
                captured_at,
            ),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_snapshot_index(
            snapshot_id,creator_id,captured_at,profile_complete,pipeline_complete,module_statuses,metric_statuses,
            followers_count,monthly_deep_users_count,interaction_rate_value_raw,completion_rate_value_raw)
            VALUES(%s,%s,%s,true,true,%s,%s,%s,%s,%s,%s)""",
            (
                snapshot_id,
                creator_id,
                captured_at,
                Jsonb({"basic": "COLLECTED"}),
                Jsonb({"followers": "COLLECTED"}),
                5704674,
                48899000,
                428,
                6343,
            ),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_quote_observations(
            snapshot_id,creator_id,position,cooperation_form,settlement_description,price_raw,offer_raw,observed_at)
            VALUES(%s,%s,0,%s,%s,%s,%s,%s)""",
            (
                snapshot_id,
                creator_id,
                "植入视频",
                "固定价格",
                60000,
                Jsonb({"desc": "植入视频", "price": 60000}),
                captured_at,
            ),
        )
    return creator_id, snapshot_id


def test_creator_library_query_reads_raw_metrics_history_quotes_and_filters(repo, plan):
    creator_id, snapshot_id = _seed_creator_library(repo, plan)
    queries = ProductQueries(repo)

    page = queries.list_creator_library(
        industry="食品饮料",
        creator_type="生活",
        followers_min=5_000_000,
        cooperation_form="植入视频",
    )
    assert [item.creator_id for item in page.items] == [creator_id]
    assert page.items[0].monthly_deep_users.raw_value == "4,889.9w"
    assert page.items[0].monthly_deep_users.is_approximate
    assert page.items[0].interaction_rate.raw_value == "428"

    detail = queries.get_creator_library(creator_id)
    assert detail.collected_field_count == 80
    assert detail.expected_cpm_21_60.raw_value == "10029"
    assert detail.field_sources["followers_count"]["source_contract"] == "test-v1"

    history = queries.creator_library_history(creator_id)
    assert history.items[0].snapshot_id == snapshot_id
    assert history.items[0].metrics["followers_count"] == 5704674
    quotes = queries.creator_library_quotes(creator_id)
    assert quotes[0].cooperation_form == "植入视频"
    assert quotes[0].price_raw == 60000


def test_creator_library_api_requires_login_and_returns_library_views(repo, plan):
    creator_id, _ = _seed_creator_library(repo, plan)
    products = ProductRepository(repo)
    passwords = PasswordService()
    products.create_user(
        "library-user", "达人库用户", passwords.hash("a-secure-password"), actor="test"
    )
    registry_path = Path("contracts/douyin_xingtu.verified.json")
    services = ProductServices(
        auth=AuthService(products, MemoryLoginLimiter(), passwords=passwords),
        products=products,
        queries=ProductQueries(repo),
        registry=PlatformRegistry.model_validate_json(registry_path.read_text()),
        covers=object(),
        settings=ProductSettings(
            database_url=repo.dsn,
            redis_url="unused",
            login_hmac_key=b"x" * 32,
            registry_path=registry_path,
            secure_cookie=True,
            allowed_origins=("https://app.test",),
            cover_config=ProductCoverConfig(
                kind="local", directory=Path(".runtime/covers"), allowed_root=Path(".runtime")
            ),
        ),
    )
    client = TestClient(create_app(services), base_url="https://app.test")
    assert client.get("/api/creator-library").status_code == 401
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": "library-user", "password": "a-secure-password"},
    )
    assert login.status_code == 200
    page = client.get("/api/creator-library?industry=%E9%A3%9F%E5%93%81%E9%A5%AE%E6%96%99")
    assert page.status_code == 200
    assert page.json()["items"][0]["creator_id"] == creator_id
    assert client.get(f"/api/creator-library/{creator_id}/history").status_code == 200
    quotes = client.get(f"/api/creator-library/{creator_id}/quotes")
    assert quotes.json()[0]["cooperation_form"] == "植入视频"


def test_creator_library_writer_keeps_last_success_when_a_field_later_fails(repo, plan):
    creator_id, snapshot_id = _seed_creator_library(repo, plan)
    observed_at = datetime(2026, 10, 13, 8, 9, tzinfo=UTC)
    collected_followers = {
        "field_key": "followers",
        "status": "COLLECTED",
        "value": {"kind": "number", "amount": "5800000"},
        "raw_value": "5800000",
        "unit": "count",
        "observed_at": observed_at.isoformat(),
        "source_kind": "response",
        "source_contract": "test-v2",
    }
    snapshot = {
        "profile_complete": True,
        "pipeline_complete": True,
        "modules": {
            "basic": {"status": "COLLECTED", "fields": [collected_followers]},
            "commercial": {
                "status": "COLLECTED",
                "fields": [
                    {
                        "field_key": "cooperation_offers",
                        "status": "COLLECTED",
                        "value": {
                            "kind": "structured",
                            "data": [{"desc": "定制视频", "price": "75000"}],
                        },
                    }
                ],
            },
        },
    }
    writer = CreatorLibraryWriter()
    with repo.connect() as conn:
        writer.sync(
            conn,
            creator_id=creator_id,
            platform_creator_id="creator-library-sample",
            projection={"basic.followers": collected_followers},
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=observed_at,
        )
        writer.sync(
            conn,
            creator_id=creator_id,
            platform_creator_id="creator-library-sample",
            projection={"basic.followers": {"field_key": "followers", "status": "FAILED"}},
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=observed_at,
        )
        row = conn.execute(
            "SELECT followers_count,field_sources FROM douyin_xingtu_creator_current "
            "WHERE creator_id=%s",
            (creator_id,),
        ).fetchone()
        quote = conn.execute(
            "SELECT price_raw FROM douyin_xingtu_creator_quote_observations "
            "WHERE snapshot_id=%s AND position=0",
            (snapshot_id,),
        ).fetchone()
    assert row["followers_count"] == 5800000
    assert row["field_sources"]["followers_count"]["source_contract"] == "test-v2"
    assert quote["price_raw"] == 60000
