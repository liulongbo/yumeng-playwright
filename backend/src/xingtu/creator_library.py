"""Platform-specific read-model writer for the independent creator library.

The JSONB projection and immutable snapshot remain the source of truth.  This module only
projects a deliberately small, documented set of Douyin Xingtu fields into query tables.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

# The two creation modules whose work arrays are split into the video observation table (DATA-02).
VIDEO_MODULE_KEYS = ("recent_video_performance", "recent_xingtu_video_performance")
_DATE_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _field(snapshot: dict[str, Any], field_key: str) -> dict[str, Any] | None:
    for module in (snapshot.get("modules") or {}).values():
        for field in module.get("fields") or []:
            if isinstance(field, dict) and field.get("field_key") == field_key:
                return field
    return None


def _collected_value(projection: dict[str, Any], key: str) -> Any | None:
    field = projection.get(key)
    if not field or field.get("status") != "COLLECTED":
        return None
    return field.get("value")


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _numeric(projection: dict[str, Any], key: str) -> tuple[Decimal | None, str | None, bool]:
    field = projection.get(key) or {}
    if field.get("status") != "COLLECTED":
        return None, None, False
    value = field.get("value") or {}
    if not isinstance(value, dict):
        return None, None, False
    return (
        _decimal(value.get("amount")),
        field.get("raw_value"),
        bool(field.get("is_approximate") or value.get("bound") == "approximate"),
    )


def _structured_number(projection: dict[str, Any], key: str, member: str) -> Decimal | None:
    value = _collected_value(projection, key)
    if not isinstance(value, dict):
        return None
    data = value.get("data")
    return _decimal(data.get(member)) if isinstance(data, dict) else None


def _structured_value(projection: dict[str, Any], key: str, member: str) -> Decimal | None:
    value = _collected_value(projection, key)
    if not isinstance(value, dict):
        return None
    return (
        _decimal(value.get("data", {}).get(member)) if isinstance(value.get("data"), dict) else None
    )


def _structured_scalar(projection: dict[str, Any], key: str) -> Decimal | None:
    """A `structured` leaf whose `data` *is* the value (`spread.average_duration` etc.).

    Those four averages arrive as `{"kind": "structured", "data": "19112"}` — a bare leaf, not a
    member object like `interaction_rate`.  Reading them through :func:`_structured_value` would
    always yield ``None``, so they get their own accessor instead of a loosened shared one.
    """
    value = _collected_value(projection, key)
    if not isinstance(value, dict):
        return None
    data = value.get("data")
    return None if isinstance(data, (dict, list)) else _decimal(data)


def _structured_member(
    projection: dict[str, Any], key: str, outer: str, inner: str
) -> Decimal | None:
    """A `structured` leaf nested one level deep (`item_rate.play_mid.value`, DATA-02/CD-08)."""
    value = _collected_value(projection, key)
    if not isinstance(value, dict):
        return None
    data = value.get("data")
    if not isinstance(data, dict):
        return None
    nested = data.get(outer)
    if not isinstance(nested, dict):
        return None
    return _decimal(nested.get(inner))


def _text(projection: dict[str, Any], key: str) -> str | None:
    value = _collected_value(projection, key)
    return value if isinstance(value, str) else None


def _list(projection: dict[str, Any], key: str) -> list[str] | None:
    value = _collected_value(projection, key)
    return (
        value if isinstance(value, list) and all(isinstance(item, str) for item in value) else None
    )


def _source(field: dict[str, Any] | None) -> dict[str, Any] | None:
    if not field or field.get("status") != "COLLECTED":
        return None
    return {
        key: field.get(key)
        for key in (
            "observed_at",
            "status",
            "source_kind",
            "source_contract",
            "path_ref",
            "unit",
            "period_label",
        )
        if field.get(key) is not None
    }


def _work_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _work_number(item: dict[str, Any], *keys: str) -> Decimal | None:
    """A real platform zero stays 0; only an absent/blank leaf becomes NULL."""
    for key in keys:
        amount = _decimal(item.get(key))
        if amount is not None:
            return amount
    return None


def _work_published(item: dict[str, Any]) -> datetime | None:
    """The platform's exact publish moment: Unix-second `create_time`, else `item_date` at UTC.

    CD-05 verified `item_date == utc(create_time)` on every sampled work (15/15), so the Unix second
    is the more precise of the two and is preferred; the date form is only a fallback.
    """
    stamp = _decimal(item.get("create_time") or item.get("create_timestamp"))
    if stamp is not None and stamp > 0:
        return datetime.fromtimestamp(float(stamp), tz=UTC)
    date_text = item.get("item_date")
    if isinstance(date_text, str) and _DATE_TEXT.match(date_text.strip()):
        return datetime.fromisoformat(date_text.strip()).replace(tzinfo=UTC)
    return None


def _work_field_statuses(item: dict[str, Any]) -> dict[str, str]:
    """Per-field status for the eleven requested work fields (project rule §5.3 vocabulary).

    A field the platform never returns is `NOT_PROVIDED` — never a fabricated 0, and never a bare
    NULL that cannot be told apart from a failed read.
    """
    statuses = {
        "title": "COLLECTED" if _work_text(item, "title", "item_title") else "NOT_PROVIDED",
        "subtitle": (
            "COLLECTED" if _work_text(item, "subtitle", "item_subtitle") else "NOT_PROVIDED"
        ),
        "cover": "COLLECTED" if _work_text(item, "item_cover") else "NOT_PROVIDED",
        "favorite_count": (
            "COLLECTED"
            if _work_number(item, "favorite_count", "collect") is not None
            else "NOT_PROVIDED"
        ),
        "share_count": "COLLECTED" if "share" in item else "NOT_PROVIDED",
        "play_count": "COLLECTED" if "play" in item else "NOT_PROVIDED",
        "like_count": "COLLECTED" if "like" in item else "NOT_PROVIDED",
        "comment_count": "COLLECTED" if "comment" in item else "NOT_PROVIDED",
        "platform_item_id": "COLLECTED" if _work_text(item, "item_id") else "NOT_PROVIDED",
        "platform_video_id": "COLLECTED" if _work_text(item, "video_id") else "NOT_PROVIDED",
        "platform_author_id": "COLLECTED" if _work_text(item, "core_user_id") else "NOT_PROVIDED",
        "published_at": "COLLECTED" if _work_published(item) else "NOT_PROVIDED",
    }
    return statuses


def _content_id(conn: Any, platform_item_id: str | None, work_url: str | None) -> str | None:
    """This platform's own work id, reused across snapshots and modules.

    Mirrors ``Repository._content_id`` (kept local because ``repository`` imports this module and a
    reverse import would be circular).  The platform's own `item_id` is the stable key: the share
    link changes on every observation (`ts`, `share_sign`), so it is only a fallback identity.
    """
    if not platform_item_id and not work_url:
        return None
    conn.execute(
        """INSERT INTO contents(content_id,platform,platform_content_id,canonical_link)
        VALUES(%s,'douyin_xingtu',%s,%s) ON CONFLICT DO NOTHING""",
        (str(uuid4()), platform_item_id, work_url),
    )
    if platform_item_id:
        row = conn.execute(
            "SELECT content_id FROM contents WHERE platform='douyin_xingtu' "
            "AND platform_content_id=%s",
            (platform_item_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT content_id FROM contents WHERE platform='douyin_xingtu' AND canonical_link=%s",
            (work_url,),
        ).fetchone()
    return str(row["content_id"]) if row else None


class CreatorLibraryWriter:
    """Keep query-only library tables in the same transaction as snapshot publication."""

    _source_fields = {
        "display_name": "basic.nickname",
        "avatar_uri": "basic.avatar_uri",
        "creator_type_label": "basic.creator_type_label",
        "province": "basic.province",
        "city": "basic.city",
        "mcn_name": "basic.mcn_name",
        "industry_labels": "basic.industry_labels",
        "content_theme_labels": "basic.content_theme_labels",
        "introduction": "basic.introduction",
        "followers_count": "basic.followers",
        "monthly_deep_users_count": "basic.monthly_deep_users",
        "monthly_connected_users_count": "fans.monthly_connected_users",
        "monthly_follower_growth_rate_raw": "basic.monthly_follower_growth_rate",
        "interaction_rate_value_raw": "spread.interaction_rate",
        "completion_rate_value_raw": "spread.completion_rate",
        "play_median_value_raw": "spread.item_rate_metrics",
        "average_duration_value_raw": "spread.average_duration",
        "average_likes_value_raw": "spread.average_likes",
        "average_comments_value_raw": "spread.average_comments",
        "average_shares_value_raw": "spread.average_shares",
        "expected_cpm_21_60_raw": "spread.expected_cpm",
        "expected_cpm_60_plus_raw": "spread.expected_cpm",
        "expected_cpe_21_60_raw": "spread.expected_cpe",
        "expected_cpe_60_plus_raw": "spread.expected_cpe",
    }

    def sync(
        self,
        conn: Any,
        *,
        creator_id: str,
        platform_creator_id: str,
        projection: dict[str, Any],
        snapshot_id: str,
        snapshot: dict[str, Any],
        captured_at: datetime,
    ) -> None:
        followers, followers_raw, followers_approximate = _numeric(projection, "basic.followers")
        deep_users, deep_users_raw, deep_users_approximate = _numeric(
            projection, "basic.monthly_deep_users"
        )
        connected_users, _, _ = _numeric(projection, "fans.monthly_connected_users")
        growth, _, _ = _numeric(projection, "basic.monthly_follower_growth_rate")
        sources = {
            name: source
            for name, key in self._source_fields.items()
            if (source := _source(projection.get(key))) is not None
        }
        fields = [
            field
            for module in (snapshot.get("modules") or {}).values()
            for field in module.get("fields") or []
        ]
        collected = sum(field.get("status") == "COLLECTED" for field in fields)
        failed = sum(field.get("status") == "FAILED" for field in fields)
        self._upsert_current(
            conn,
            creator_id=creator_id,
            platform_creator_id=platform_creator_id,
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=captured_at,
            display_name=_text(projection, "basic.nickname"),
            avatar_uri=_text(projection, "basic.avatar_uri"),
            creator_type_label=_text(projection, "basic.creator_type_label"),
            province=_text(projection, "basic.province"),
            city=_text(projection, "basic.city"),
            mcn_name=_text(projection, "basic.mcn_name"),
            industry_labels=_list(projection, "basic.industry_labels"),
            content_theme_labels=_list(projection, "basic.content_theme_labels"),
            introduction=_text(projection, "basic.introduction"),
            followers=followers,
            followers_raw=followers_raw,
            followers_approximate=followers_approximate,
            deep_users=deep_users,
            deep_users_raw=deep_users_raw,
            deep_users_approximate=deep_users_approximate,
            connected_users=connected_users,
            growth=growth,
            interaction=_structured_value(projection, "spread.interaction_rate", "value"),
            completion=_structured_value(projection, "spread.completion_rate", "value"),
            play_median=_structured_member(
                projection, "spread.item_rate_metrics", "play_mid", "value"
            ),
            average_duration=_structured_scalar(projection, "spread.average_duration"),
            average_likes=_structured_scalar(projection, "spread.average_likes"),
            average_comments=_structured_scalar(projection, "spread.average_comments"),
            average_shares=_structured_scalar(projection, "spread.average_shares"),
            cpm_21_60=_structured_number(projection, "spread.expected_cpm", "cpm_21_60"),
            cpm_60_plus=_structured_number(projection, "spread.expected_cpm", "cpm_60"),
            cpe_21_60=_structured_number(projection, "spread.expected_cpe", "cpe_21_60"),
            cpe_60_plus=_structured_number(projection, "spread.expected_cpe", "cpe_60"),
            collected=collected,
            failed=failed,
            sources=sources,
        )
        self._insert_snapshot_index(conn, creator_id, snapshot_id, snapshot, captured_at)
        self._insert_quotes(conn, creator_id, snapshot_id, snapshot, captured_at)
        self._insert_video_observations(
            conn,
            creator_id=creator_id,
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=captured_at,
        )

    def _upsert_current(self, conn: Any, **value: Any) -> None:
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_current(
            creator_id,platform_creator_id,latest_snapshot_id,display_name,avatar_uri,
            creator_type_label,province,city,mcn_name,industry_labels,content_theme_labels,
            introduction,followers_count,followers_raw,followers_is_approximate,
            monthly_deep_users_count,monthly_deep_users_raw,monthly_deep_users_is_approximate,
            monthly_connected_users_count,monthly_follower_growth_rate_raw,
            interaction_rate_value_raw,completion_rate_value_raw,expected_cpm_21_60_raw,
            expected_cpm_60_plus_raw,expected_cpe_21_60_raw,expected_cpe_60_plus_raw,
            play_median_value_raw,average_duration_value_raw,average_likes_value_raw,
            average_comments_value_raw,average_shares_value_raw,
            profile_complete,pipeline_complete,collected_field_count,failed_field_count,
            field_sources,data_updated_at)
            VALUES(%(creator_id)s,%(platform_creator_id)s,%(snapshot_id)s,%(display_name)s,%(avatar_uri)s,
            %(creator_type_label)s,%(province)s,%(city)s,%(mcn_name)s,%(industry_labels)s,%(content_theme_labels)s,
            %(introduction)s,%(followers)s,%(followers_raw)s,%(followers_approximate)s,
            %(deep_users)s,%(deep_users_raw)s,%(deep_users_approximate)s,%(connected_users)s,%(growth)s,
            %(interaction)s,%(completion)s,%(cpm_21_60)s,%(cpm_60_plus)s,%(cpe_21_60)s,%(cpe_60_plus)s,
            %(play_median)s,%(average_duration)s,%(average_likes)s,%(average_comments)s,%(average_shares)s,
            %(profile_complete)s,%(pipeline_complete)s,%(collected)s,%(failed)s,%(sources)s,%(captured_at)s)
            ON CONFLICT(creator_id) DO UPDATE SET
              latest_snapshot_id=EXCLUDED.latest_snapshot_id,
              display_name=COALESCE(EXCLUDED.display_name,douyin_xingtu_creator_current.display_name),
              avatar_uri=COALESCE(EXCLUDED.avatar_uri,douyin_xingtu_creator_current.avatar_uri),
              creator_type_label=COALESCE(EXCLUDED.creator_type_label,douyin_xingtu_creator_current.creator_type_label),
              province=COALESCE(EXCLUDED.province,douyin_xingtu_creator_current.province),
              city=COALESCE(EXCLUDED.city,douyin_xingtu_creator_current.city),
              mcn_name=COALESCE(EXCLUDED.mcn_name,douyin_xingtu_creator_current.mcn_name),
              industry_labels=CASE WHEN EXCLUDED.industry_labels='[]'::jsonb
                THEN douyin_xingtu_creator_current.industry_labels
                ELSE EXCLUDED.industry_labels END,
              content_theme_labels=CASE WHEN EXCLUDED.content_theme_labels='[]'::jsonb
                THEN douyin_xingtu_creator_current.content_theme_labels
                ELSE EXCLUDED.content_theme_labels END,
              introduction=COALESCE(EXCLUDED.introduction,douyin_xingtu_creator_current.introduction),
              followers_count=COALESCE(EXCLUDED.followers_count,douyin_xingtu_creator_current.followers_count),
              followers_raw=COALESCE(EXCLUDED.followers_raw,douyin_xingtu_creator_current.followers_raw),
              followers_is_approximate=EXCLUDED.followers_is_approximate
                OR douyin_xingtu_creator_current.followers_is_approximate,
              monthly_deep_users_count=COALESCE(EXCLUDED.monthly_deep_users_count,douyin_xingtu_creator_current.monthly_deep_users_count),
              monthly_deep_users_raw=COALESCE(EXCLUDED.monthly_deep_users_raw,douyin_xingtu_creator_current.monthly_deep_users_raw),
              monthly_deep_users_is_approximate=EXCLUDED.monthly_deep_users_is_approximate
                OR douyin_xingtu_creator_current.monthly_deep_users_is_approximate,
              monthly_connected_users_count=COALESCE(EXCLUDED.monthly_connected_users_count,douyin_xingtu_creator_current.monthly_connected_users_count),
              monthly_follower_growth_rate_raw=COALESCE(EXCLUDED.monthly_follower_growth_rate_raw,douyin_xingtu_creator_current.monthly_follower_growth_rate_raw),
              interaction_rate_value_raw=COALESCE(EXCLUDED.interaction_rate_value_raw,douyin_xingtu_creator_current.interaction_rate_value_raw),
              completion_rate_value_raw=COALESCE(EXCLUDED.completion_rate_value_raw,douyin_xingtu_creator_current.completion_rate_value_raw),
              play_median_value_raw=COALESCE(EXCLUDED.play_median_value_raw,douyin_xingtu_creator_current.play_median_value_raw),
              average_duration_value_raw=COALESCE(EXCLUDED.average_duration_value_raw,douyin_xingtu_creator_current.average_duration_value_raw),
              average_likes_value_raw=COALESCE(EXCLUDED.average_likes_value_raw,douyin_xingtu_creator_current.average_likes_value_raw),
              average_comments_value_raw=COALESCE(EXCLUDED.average_comments_value_raw,douyin_xingtu_creator_current.average_comments_value_raw),
              average_shares_value_raw=COALESCE(EXCLUDED.average_shares_value_raw,douyin_xingtu_creator_current.average_shares_value_raw),
              expected_cpm_21_60_raw=COALESCE(EXCLUDED.expected_cpm_21_60_raw,douyin_xingtu_creator_current.expected_cpm_21_60_raw),
              expected_cpm_60_plus_raw=COALESCE(EXCLUDED.expected_cpm_60_plus_raw,douyin_xingtu_creator_current.expected_cpm_60_plus_raw),
              expected_cpe_21_60_raw=COALESCE(EXCLUDED.expected_cpe_21_60_raw,douyin_xingtu_creator_current.expected_cpe_21_60_raw),
              expected_cpe_60_plus_raw=COALESCE(EXCLUDED.expected_cpe_60_plus_raw,douyin_xingtu_creator_current.expected_cpe_60_plus_raw),
              profile_complete=EXCLUDED.profile_complete,pipeline_complete=EXCLUDED.pipeline_complete,
              collected_field_count=EXCLUDED.collected_field_count,failed_field_count=EXCLUDED.failed_field_count,
              field_sources=douyin_xingtu_creator_current.field_sources || EXCLUDED.field_sources,
              data_updated_at=EXCLUDED.data_updated_at,updated_at=now()""",
            {
                **value,
                "industry_labels": Jsonb(value["industry_labels"] or []),
                "content_theme_labels": Jsonb(value["content_theme_labels"] or []),
                "profile_complete": bool(value["snapshot"].get("profile_complete")),
                "pipeline_complete": bool(value["snapshot"].get("pipeline_complete")),
                "sources": Jsonb(value["sources"]),
            },
        )

    def _insert_snapshot_index(
        self,
        conn: Any,
        creator_id: str,
        snapshot_id: str,
        snapshot: dict[str, Any],
        captured_at: datetime,
    ) -> None:
        statuses = {
            module_key: module.get("status")
            for module_key, module in (snapshot.get("modules") or {}).items()
        }
        metric_fields = (
            "followers",
            "monthly_deep_users",
            "monthly_connected_users",
            "monthly_follower_growth_rate",
            "interaction_rate",
            "completion_rate",
            "item_rate_metrics",
            "average_duration",
            "average_likes",
            "average_comments",
            "average_shares",
            "expected_cpm",
            "expected_cpe",
        )
        metric_statuses = {
            key: (_field(snapshot, key) or {}).get("status") for key in metric_fields
        }

        def amount(key: str) -> Decimal | None:
            field = _field(snapshot, key) or {}
            value = field.get("value") or {}
            return _decimal(value.get("amount")) if isinstance(value, dict) else None

        def member(key: str, name: str) -> Decimal | None:
            field = _field(snapshot, key) or {}
            value = field.get("value") or {}
            data = value.get("data") if isinstance(value, dict) else None
            return _decimal(data.get(name)) if isinstance(data, dict) else None

        def scalar(key: str) -> Decimal | None:
            field = _field(snapshot, key) or {}
            value = field.get("value") or {}
            data = value.get("data") if isinstance(value, dict) else None
            return None if isinstance(data, (dict, list)) else _decimal(data)

        def nested(key: str, outer: str, inner: str) -> Decimal | None:
            field = _field(snapshot, key) or {}
            value = field.get("value") or {}
            data = value.get("data") if isinstance(value, dict) else None
            if not isinstance(data, dict) or not isinstance(data.get(outer), dict):
                return None
            return _decimal(data[outer].get(inner))

        conn.execute(
            """INSERT INTO douyin_xingtu_creator_snapshot_index(
            snapshot_id,creator_id,captured_at,profile_complete,pipeline_complete,module_statuses,metric_statuses,
            followers_count,monthly_deep_users_count,monthly_connected_users_count,monthly_follower_growth_rate_raw,
            interaction_rate_value_raw,completion_rate_value_raw,expected_cpm_21_60_raw,expected_cpm_60_plus_raw,
            expected_cpe_21_60_raw,expected_cpe_60_plus_raw,
            play_median_value_raw,average_duration_value_raw,average_likes_value_raw,
            average_comments_value_raw,average_shares_value_raw)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(snapshot_id) DO NOTHING""",
            (
                snapshot_id,
                creator_id,
                captured_at,
                bool(snapshot.get("profile_complete")),
                bool(snapshot.get("pipeline_complete")),
                Jsonb(statuses),
                Jsonb(metric_statuses),
                amount("followers"),
                amount("monthly_deep_users"),
                amount("monthly_connected_users"),
                amount("monthly_follower_growth_rate"),
                member("interaction_rate", "value"),
                member("completion_rate", "value"),
                member("expected_cpm", "cpm_21_60"),
                member("expected_cpm", "cpm_60"),
                member("expected_cpe", "cpe_21_60"),
                member("expected_cpe", "cpe_60"),
                nested("item_rate_metrics", "play_mid", "value"),
                scalar("average_duration"),
                scalar("average_likes"),
                scalar("average_comments"),
                scalar("average_shares"),
            ),
        )

    def _insert_video_observations(
        self,
        conn: Any,
        *,
        creator_id: str,
        snapshot_id: str,
        snapshot: dict[str, Any],
        captured_at: datetime,
    ) -> None:
        """Append one work observation per collected work record (DATA-02).

        Mirrors the 015 backfill exactly, so a re-collected creator and a migrated creator end up
        with the same rows.  The append-only trigger means a repeated sync for the same snapshot is
        a no-op rather than an overwrite.
        """
        creation = (snapshot.get("modules") or {}).get("creation") or {}
        for field in creation.get("fields") or []:
            module_key = field.get("field_key")
            if module_key not in VIDEO_MODULE_KEYS or field.get("status") != "COLLECTED":
                continue
            value = field.get("value")
            items = value.get("data") if isinstance(value, dict) else None
            if not isinstance(items, list):
                continue
            observed_at = captured_at
            if isinstance(field.get("observed_at"), str):
                try:
                    observed_at = datetime.fromisoformat(field["observed_at"])
                except ValueError:
                    observed_at = captured_at
            for position, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                platform_item_id = _work_text(item, "item_id")
                work_url = _work_text(item, "url")
                conn.execute(
                    """INSERT INTO douyin_xingtu_creator_video_observations(
                    snapshot_id,creator_id,module_key,position,content_id,platform_item_id,
                    platform_video_id,platform_author_id,title,subtitle,published_at,published_raw,
                    play_count,like_count,comment_count,favorite_count,share_count,cover_source_uri,
                    work_url,field_statuses,observed_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(snapshot_id,module_key,position) DO NOTHING""",
                    (
                        snapshot_id,
                        creator_id,
                        module_key,
                        position,
                        _content_id(conn, platform_item_id, work_url),
                        platform_item_id,
                        _work_text(item, "video_id"),
                        _work_text(item, "core_user_id"),
                        _work_text(item, "title", "item_title"),
                        None,
                        _work_published(item),
                        _work_text(item, "item_date", "create_time"),
                        _work_number(item, "play"),
                        _work_number(item, "like"),
                        _work_number(item, "comment"),
                        _work_number(item, "favorite_count", "collect"),
                        _work_number(item, "share"),
                        _work_text(item, "item_cover"),
                        work_url,
                        Jsonb(_work_field_statuses(item)),
                        observed_at,
                    ),
                )

    def _insert_quotes(
        self,
        conn: Any,
        creator_id: str,
        snapshot_id: str,
        snapshot: dict[str, Any],
        captured_at: datetime,
    ) -> None:
        observation = _field(snapshot, "cooperation_offers") or {}
        value = observation.get("value") or {}
        offers = value.get("data") if isinstance(value, dict) else None
        if observation.get("status") != "COLLECTED" or not isinstance(offers, list):
            return
        for position, offer in enumerate(offers):
            if not isinstance(offer, dict):
                continue
            conn.execute(
                """INSERT INTO douyin_xingtu_creator_quote_observations(
                snapshot_id,creator_id,position,cooperation_form,settlement_description,price_raw,
                origin_price_raw,offer_raw,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(snapshot_id,position) DO NOTHING""",
                (
                    snapshot_id,
                    creator_id,
                    position,
                    offer.get("desc") or offer.get("field"),
                    offer.get("settlement_desc"),
                    _decimal(offer.get("price")),
                    _decimal(offer.get("origin_price")),
                    Jsonb(offer),
                    captured_at,
                ),
            )
