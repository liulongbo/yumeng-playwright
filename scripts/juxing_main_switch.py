#!/usr/bin/env python3
"""JUXING-MAIN-01 switch tooling: read-only baseline, preflight, comparison and session probe.

The tool is deliberately conservative:

* ``baseline`` and ``compare`` only read the business database.
* ``preflight`` validates a *candidate* config and environment additions without applying them; it
  never writes the live main configuration and never registers a platform binding.
* ``session-check`` is an explicit, read-only platform probe: it opens the juxing protected page,
  reads the bound sub-account, and closes. It never collects creators and never selects a
  sub-account. Cookies, tokens and the DSN are never printed.

Commands::

    python scripts/juxing_main_switch.py baseline --out .runtime/juxing-main/baseline.json
    python scripts/juxing_main_switch.py preflight --candidate-config ... --additions-env ...
    python scripts/juxing_main_switch.py compare --baseline .runtime/juxing-main/baseline.json
    python scripts/juxing_main_switch.py session-check --config .runtime/units/local-dev-mac-02.json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

DEFAULT_UNIT = "unit-local-mac-02"
DEFAULT_JUXING_ACCOUNT = "60821564"
DEFAULT_RUNTIME_ROOT = ROOT / ".runtime"
DEFAULT_ENV_FILE = ROOT / ".runtime" / "m3-app.env"
DEFAULT_CONFIG = ROOT / ".runtime" / "units" / "local-dev-mac-02.json"
DEFAULT_OUT = ROOT / ".runtime" / "juxing-main"
JUXING_ADDITION_KEYS = {
    "XINGTU_ENABLE_KUAISHOU_JUXING",
    "XINGTU_JUXING_REGISTRY_PATH",
    "XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT",
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def private_mode(path: Path) -> bool:
    try:
        return stat.S_IMODE(path.stat().st_mode) in {0o600, 0o400}
    except OSError:
        return False


def private_dir_mode(path: Path) -> bool:
    try:
        return stat.S_IMODE(path.stat().st_mode) in {0o700, 0o500}
    except OSError:
        return False


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _dsn(env: dict[str, str], explicit: str | None) -> str:
    value = explicit or env.get("XINGTU_DATABASE_URL", "")
    if not value:
        raise SystemExit("XINGTU_DATABASE_URL missing (use --env-file or --database-url)")
    return value


def _connect(dsn: str) -> Any:
    import psycopg

    connection = psycopg.connect(dsn)
    # ``row::text`` renders timestamptz in the session timezone.  The main database defaults to
    # Asia/Shanghai while the isolated restore cluster defaults to UTC, so every comparison must
    # pin one timezone or identical rows would hash differently across clusters.
    connection.execute("SET TIME ZONE 'UTC'")
    return connection


def _hash_query(connection: Any, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    row = connection.execute(sql, params).fetchone()
    return {"count": int(row[0]), "md5": str(row[1])}


def compute_baseline(
    dsn: str,
    unit_id: str,
    *,
    root_ids: list[str] | None = None,
    creator_ids: list[str] | None = None,
    schedule_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Read-only content baseline scoped to the star-chart business data that must not change.

    ``compare`` passes the IDs captured at baseline time so a newly authorized star-chart task can
    never make the historical rows look modified.
    """

    with _connect(dsn) as connection:
        if root_ids is None:
            root_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT root_task_id::text FROM root_tasks WHERE platform='douyin_xingtu' "
                    "ORDER BY root_task_id"
                ).fetchall()
            ]
        if creator_ids is None:
            creator_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT creator_id::text FROM platform_creators WHERE platform='douyin_xingtu' "
                    "ORDER BY creator_id"
                ).fetchall()
            ]
        if schedule_ids is None:
            schedule_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT creator_id::text FROM creator_update_schedule ORDER BY creator_id"
                ).fetchall()
            ]
        hashes: dict[str, dict[str, Any]] = {}
        scoped = {
            "root_tasks": (
                "root_task_id = ANY(%s)",
                "root_task_id",
                (root_ids,),
            ),
            "platform_creators": (
                "creator_id = ANY(%s) AND platform='douyin_xingtu'",
                "creator_id",
                (creator_ids,),
            ),
            "task_creators": (
                "root_task_id = ANY(%s)",
                "root_task_id,creator_id",
                (root_ids,),
            ),
            "creator_snapshots": (
                "root_task_id = ANY(%s)",
                "snapshot_id",
                (root_ids,),
            ),
            "douyin_xingtu_creator_current": (
                "creator_id = ANY(%s)",
                "creator_id",
                (creator_ids,),
            ),
            "douyin_xingtu_creator_snapshot_index": (
                "creator_id = ANY(%s)",
                "snapshot_id",
                (creator_ids,),
            ),
            "douyin_xingtu_creator_quote_observations": (
                "creator_id = ANY(%s)",
                "snapshot_id,position",
                (creator_ids,),
            ),
            "douyin_xingtu_creator_video_observations": (
                "creator_id = ANY(%s)",
                "snapshot_id,module_key,position",
                (creator_ids,),
            ),
            "requirements": (
                "root_task_id = ANY(%s)",
                "root_task_id",
                (root_ids,),
            ),
            "filter_plans": (
                "root_task_id = ANY(%s)",
                "root_task_id",
                (root_ids,),
            ),
            "task_dispatches": (
                "root_task_id = ANY(%s)",
                "root_task_id,segment",
                (root_ids,),
            ),
            "featured_collections": (
                "root_task_id = ANY(%s)",
                "collection_observation_id",
                (root_ids,),
            ),
            "raw_evidence": (
                "root_task_id = ANY(%s)",
                "object_id",
                (root_ids,),
            ),
            "media_objects": (
                "root_task_id = ANY(%s)",
                "object_id",
                (root_ids,),
            ),
            "creator_update_schedule": (
                "creator_id = ANY(%s)",
                "creator_id",
                (schedule_ids,),
            ),
        }
        for table, (where, order_by, params) in scoped.items():
            hashes[table] = _hash_query(
                connection,
                "SELECT count(*), md5(coalesce(string_agg(md5(t::text), ',' "
                f"ORDER BY {order_by}), '')) FROM {table} t WHERE {where}",
                params,
            )
        hashes["task_checkpoints"] = _hash_query(
            connection,
            "SELECT count(*), md5(coalesce(string_agg(md5(t::text), ',' "
            "ORDER BY task_id,revision),''))"
            " FROM task_checkpoints t WHERE task_id IN "
            "(SELECT task_id FROM tasks WHERE root_task_id = ANY(%s))",
            (root_ids,),
        )
        hashes["featured_cards"] = _hash_query(
            connection,
            "SELECT count(*), md5(coalesce(string_agg(md5(t::text), ',' "
            "ORDER BY collection_observation_id,card_id),'')) FROM featured_cards t "
            "WHERE collection_observation_id IN (SELECT collection_observation_id "
            "FROM featured_collections WHERE root_task_id = ANY(%s))",
            (root_ids,),
        )
        unit_row = connection.execute(
            "SELECT unit_id,account_ref,line_ref,profile_ref,network_mode,expected_account_id "
            "FROM execution_units WHERE unit_id=%s",
            (unit_id,),
        ).fetchone()
        binding_row = connection.execute(
            "SELECT unit_id,platform,account_ref,expected_account_id,"
            "profile_ref,registry_ref,enabled "
            "FROM execution_unit_platform_bindings WHERE unit_id=%s AND platform='douyin_xingtu'",
            (unit_id,),
        ).fetchone()
        table_counts = {
            name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            for name in (
                "root_tasks",
                "platform_creators",
                "task_creators",
                "creator_snapshots",
                "creator_update_schedule",
                "verification_events",
                "browser_takeover_sessions",
                "audit_logs",
                "users",
                "sessions",
            )
        }
        by_platform = {
            f"{row[0]}/{row[1]}": row[2]
            for row in connection.execute(
                "SELECT platform,state,count(*) FROM root_tasks GROUP BY 1,2 ORDER BY 1,2"
            ).fetchall()
        }
        creators_by_platform = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT platform,count(*) FROM platform_creators GROUP BY 1 ORDER BY 1"
            ).fetchall()
        }
        schema_version = connection.execute(
            "SELECT max(version) FROM schema_migrations"
        ).fetchone()[0]
    return {
        "schema_version": "juxing_main_baseline.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "database": "xingtu_development",
        "unit_id": unit_id,
        "migration_version": int(schema_version),
        "xingtu_root_task_ids": root_ids,
        "xingtu_creator_ids": creator_ids,
        "update_schedule_creator_ids": schedule_ids,
        "counts": table_counts,
        "root_tasks_by_platform_state": by_platform,
        "creators_by_platform": creators_by_platform,
        "hashes": hashes,
        "unit_immutable": dict(
            zip(
                (
                    "unit_id",
                    "account_ref",
                    "line_ref",
                    "profile_ref",
                    "network_mode",
                    "expected_account_id",
                ),
                unit_row,
                strict=False,
            )
        )
        if unit_row
        else None,
        "xingtu_binding_immutable": dict(
            zip(
                (
                    "unit_id",
                    "platform",
                    "account_ref",
                    "expected_account_id",
                    "profile_ref",
                    "registry_ref",
                    "enabled",
                ),
                binding_row,
                strict=False,
            )
        )
        if binding_row
        else None,
    }


def compare_baseline(dsn: str, baseline: dict[str, Any]) -> list[dict[str, Any]]:
    expected = baseline["hashes"]
    current = compute_baseline(
        dsn,
        baseline["unit_id"],
        root_ids=list(baseline["xingtu_root_task_ids"]),
        creator_ids=list(baseline["xingtu_creator_ids"]),
        schedule_ids=list(baseline["update_schedule_creator_ids"]),
    )
    differences: list[dict[str, Any]] = []
    for name, before in expected.items():
        after = current["hashes"].get(name)
        if after != before:
            differences.append({"scope": name, "before": before, "after": after})
    if baseline["unit_immutable"] != current["unit_immutable"]:
        differences.append(
            {
                "scope": "execution_units.immutable",
                "before": baseline["unit_immutable"],
                "after": current["unit_immutable"],
            }
        )
    if baseline["xingtu_binding_immutable"] != current["xingtu_binding_immutable"]:
        differences.append(
            {
                "scope": "execution_unit_platform_bindings.xingtu",
                "before": baseline["xingtu_binding_immutable"],
                "after": current["xingtu_binding_immutable"],
            }
        )
    return differences


# --- preflight -------------------------------------------------------------------------------


def _binding_for(unit: Any, platform: str) -> Any | None:
    from xingtu.domain import PlatformId

    requested = PlatformId(platform)
    for binding in unit.platform_bindings:
        if binding.platform == requested:
            return binding
    return None


def _registry_live(path: Path) -> tuple[bool, str]:
    from xingtu.contracts import PlatformRegistry

    try:
        registry = PlatformRegistry.model_validate_json(path.read_text())
        registry.require_enabled(live=True)
    except Exception as exc:  # noqa: BLE001 - detail is reported, never raised
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    return True, registry.contract_version


def _profile_lock_state(profile: Path) -> str:
    from xingtu.platform_runtime import ProfileLockBusy, acquire_profile_lock, release_profile_lock

    if not profile.is_dir():
        return "PROFILE_MISSING"
    lock_path = profile.parent / (profile.name + ".lock")
    try:
        with lock_path.open("a+b") as handle:
            try:
                acquire_profile_lock(handle)
            except ProfileLockBusy:
                return "IN_USE"
            else:
                release_profile_lock(handle)
    except OSError:
        return "UNKNOWN"
    singleton = profile / "SingletonLock"
    if singleton.is_symlink():
        try:
            target = os.readlink(singleton)
            pid = int(target.rsplit("-", 1)[-1])
            os.kill(pid, 0)
        except (OSError, ValueError):
            return "STALE_SINGLETON_LOCK"
        return "IN_USE"
    return "FREE"


def _snapshot_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
        storage = payload.get("storage_state") or {}
        cookies = storage.get("cookies") or []
        domains = sorted({str(cookie.get("domain") or "") for cookie in cookies})
        return {
            "exists": True,
            "byte_size": path.stat().st_size,
            "schema_version": payload.get("schema_version"),
            "unit_id": payload.get("unit_id"),
            "captured_at": payload.get("captured_at"),
            "cookie_count": len(cookies),
            "cookie_domains": domains,
        }
    except (OSError, ValueError):
        return {"exists": path.is_file(), "readable": False}


def config_checks(
    live_config: Path,
    candidate_config: Path | None,
    runtime_root: Path,
    expected_unit: str,
    expected_account: str,
) -> list[Check]:
    from xingtu.domain import PlatformId
    from xingtu.runtime import load_unit

    checks: list[Check] = []
    checks.append(Check("LIVE_CONFIG_EXISTS", live_config.is_file(), str(live_config)))
    checks.append(Check("LIVE_CONFIG_PRIVATE", private_mode(live_config), "mode must be 0600"))
    try:
        live = load_unit(live_config)
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("LIVE_CONFIG_VALID", False, f"{type(exc).__name__}: {exc}"))
        return checks
    checks.append(Check("LIVE_CONFIG_VALID", True, f"unit_id={live.unit_id}"))
    checks.append(Check("LIVE_UNIT_ID", live.unit_id == expected_unit, f"unit_id={live.unit_id}"))
    live_juxing = _binding_for(live, "kuaishou_juxing")
    checks.append(
        Check(
            "LIVE_HAS_NO_JUXING_BINDING_YET",
            live_juxing is None,
            "live config must stay star-chart-only until the switch is authorized",
        )
    )
    if candidate_config is None:
        checks.append(
            Check(
                "CANDIDATE_CONFIG_PRESENT", False, "no --candidate-config supplied", required=False
            )
        )
        return checks
    checks.append(
        Check("CANDIDATE_CONFIG_EXISTS", candidate_config.is_file(), str(candidate_config))
    )
    checks.append(
        Check("CANDIDATE_CONFIG_PRIVATE", private_mode(candidate_config), "mode must be 0600")
    )
    try:
        candidate = load_unit(candidate_config)
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("CANDIDATE_CONFIG_VALID", False, f"{type(exc).__name__}: {exc}"))
        return checks
    checks.append(Check("CANDIDATE_CONFIG_VALID", True, f"unit_id={candidate.unit_id}"))
    checks.append(
        Check(
            "CANDIDATE_UNIT_ID", candidate.unit_id == expected_unit, f"unit_id={candidate.unit_id}"
        )
    )
    unchanged = live.model_dump(exclude={"platform_bindings"}) == candidate.model_dump(
        exclude={"platform_bindings"}
    )
    checks.append(
        Check(
            "CANDIDATE_ONLY_ADDS_BINDING",
            unchanged,
            "candidate must not change star-chart fields, only add the juxing binding",
        )
    )
    juxing_bindings = [
        binding
        for binding in candidate.platform_bindings
        if binding.platform == PlatformId.KUAISHOU_JUXING
    ]
    checks.append(
        Check(
            "CANDIDATE_HAS_ONE_JUXING_BINDING",
            len(juxing_bindings) == 1,
            f"juxing bindings={len(juxing_bindings)}",
        )
    )
    if len(juxing_bindings) != 1:
        return checks
    binding = juxing_bindings[0]
    checks.append(Check("JUXING_BINDING_ENABLED", binding.enabled, "binding must be enabled"))
    checks.append(
        Check(
            "JUXING_ACCOUNT_ID",
            binding.expected_account_id == expected_account,
            f"expected={expected_account} actual={binding.expected_account_id}",
        )
    )
    profile = binding.profile_directory.resolve()
    inside = profile.is_relative_to(runtime_root.resolve()) and profile != runtime_root.resolve()
    checks.append(Check("JUXING_PROFILE_INSIDE_RUNTIME", inside, str(profile)))
    checks.append(
        Check(
            "JUXING_PROFILE_DISTINCT_FROM_XINGTU",
            profile != live.profile_directory.resolve(),
            "juxing and xingtu must not share a Chrome profile",
        )
    )
    checks.append(Check("JUXING_PROFILE_DIR_EXISTS", profile.is_dir(), str(profile)))
    if profile.is_dir():
        checks.append(
            Check(
                "JUXING_PROFILE_PERMISSIONS",
                stat.S_IMODE(profile.stat().st_mode) == 0o700,
                "profile directory must be 0700",
            )
        )
    juxing_lock = _profile_lock_state(profile)
    checks.append(Check("JUXING_PROFILE_LOCK", juxing_lock == "FREE", juxing_lock))
    xingtu_profile = live.profile_directory.resolve()
    xingtu_lock = _profile_lock_state(xingtu_profile)
    checks.append(Check("XINGTU_PROFILE_LOCK", xingtu_lock == "FREE", xingtu_lock))
    registry_live, registry_detail = _registry_live(binding.registry_path)
    checks.append(Check("JUXING_REGISTRY_LIVE", registry_live, registry_detail))
    snapshot = (
        runtime_root.resolve() / "storage-state" / (f"{candidate.unit_id}.kuaishou_juxing.json")
    )
    metadata = _snapshot_metadata(snapshot)
    checks.append(
        Check(
            "JUXING_SNAPSHOT_PRESENT",
            bool(metadata.get("exists")),
            json.dumps(metadata, ensure_ascii=False)[:300],
        )
    )
    if metadata.get("exists"):
        checks.append(
            Check(
                "JUXING_SNAPSHOT_PRIVATE",
                private_mode(snapshot),
                "snapshot must be 0600",
            )
        )
    checks.append(
        Check(
            "JUXING_SNAPSHOT_UNIT_ID",
            metadata.get("unit_id") == candidate.unit_id,
            f"snapshot unit_id={metadata.get('unit_id')} expected={candidate.unit_id}",
            required=False,
        )
    )
    checks.append(
        Check(
            "XINGTU_PROFILE_DISTINCT",
            xingtu_profile != profile,
            "distinct profile directories",
        )
    )
    return checks


def env_checks(
    live_env: dict[str, str], additions: dict[str, str], runtime_root: Path
) -> list[Check]:
    del runtime_root
    checks: list[Check] = []
    unknown = sorted(set(additions) - JUXING_ADDITION_KEYS)
    checks.append(
        Check(
            "ENV_ADDITIONS_SCOPE",
            not unknown,
            f"unexpected keys={unknown}" if unknown else "only the three juxing keys are added",
        )
    )
    effective = {**live_env, **additions}
    flag = effective.get("XINGTU_ENABLE_KUAISHOU_JUXING", "0").lower() in {"1", "true", "yes"}
    checks.append(
        Check(
            "EFFECTIVE_JUXING_FLAG",
            flag,
            f"XINGTU_ENABLE_KUAISHOU_JUXING={effective.get('XINGTU_ENABLE_KUAISHOU_JUXING')}",
        )
    )
    registry = effective.get("XINGTU_JUXING_REGISTRY_PATH", "")
    registry_path = Path(registry) if registry else Path("contracts/kuaishou_juxing.verified.json")
    checks.append(
        Check(
            "EFFECTIVE_JUXING_REGISTRY_PATH",
            registry_path.is_file(),
            str(registry_path),
        )
    )
    raw_limit = effective.get("XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT", "3")
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 0
    checks.append(
        Check(
            "EFFECTIVE_JUXING_MAX_TARGET",
            1 <= limit <= 200,
            f"value={limit} (current product decision: 30; long-term ceiling: 200)",
        )
    )
    checks.append(
        Check(
            "JUXING_MAX_TARGET_IS_30",
            limit == 30,
            f"value={limit}; expected 30 for the current main-station phase",
        )
    )
    return checks


def db_checks(
    dsn: str,
    unit_id: str,
    stage: str,
    expected_account: str | None,
    candidate_profile: Path | None,
    candidate_account_ref: str | None,
) -> tuple[list[Check], dict[str, Any]]:
    from xingtu.repository import Repository

    checks: list[Check] = []
    info: dict[str, Any] = {}
    repository = Repository(dsn)
    with _connect(dsn) as connection:
        version = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        checks.append(
            Check("DB_MIGRATIONS", int(version) >= 20, f"schema_migrations max={version}")
        )
        unit = connection.execute(
            "SELECT state,owner,lease_until,current_root_task_id,browser_stopped "
            "FROM execution_units WHERE unit_id=%s",
            (unit_id,),
        ).fetchone()
        if unit is None:
            checks.append(Check("UNIT_REGISTERED", False, "unit missing"))
            return checks, info
        info["unit"] = {
            "state": unit[0],
            "owner": str(unit[1]) if unit[1] else None,
            "lease_until": str(unit[2]) if unit[2] else None,
            "current_root_task_id": str(unit[3]) if unit[3] else None,
            "browser_stopped": unit[4],
        }
        checks.append(Check("UNIT_READY", unit[0] == "READY", f"state={unit[0]}"))
        checks.append(
            Check("UNIT_NO_ACTIVE_LEASE", unit[1] is None and unit[2] is None, "owner/lease")
        )
        checks.append(
            Check(
                "UNIT_NO_CURRENT_TASK",
                unit[3] is None,
                f"current_root_task_id={unit[3]}",
            )
        )
        checks.append(Check("UNIT_BROWSER_STOPPED", bool(unit[4]), f"browser_stopped={unit[4]}"))
        checks.append(
            Check(
                "UNIT_NO_ACTIVE_CLAIM",
                not repository.has_active_unit_claim(unit_id),
                "verification/takeover/lease",
            )
        )
        bindings = connection.execute(
            "SELECT platform,account_ref,expected_account_id,profile_ref,registry_ref,enabled "
            "FROM execution_unit_platform_bindings WHERE unit_id=%s ORDER BY platform",
            (unit_id,),
        ).fetchall()
        info["bindings"] = [
            {
                "platform": row[0],
                "account_ref": row[1],
                "expected_account_id": row[2],
                "profile_ref": row[3],
                "registry_ref": row[4],
                "enabled": row[5],
            }
            for row in bindings
        ]
        platforms = {row[0]: row for row in bindings}
        checks.append(
            Check("XINGTU_BINDING_PRESENT", "douyin_xingtu" in platforms, "douyin_xingtu binding")
        )
        juxing = platforms.get("kuaishou_juxing")
        if stage == "post_switch":
            checks.append(
                Check(
                    "JUXING_BINDING_REGISTERED",
                    juxing is not None and bool(juxing[5]),
                    "kuaishou_juxing binding enabled",
                )
            )
        else:
            checks.append(
                Check(
                    "JUXING_BINDING_NOT_YET_REGISTERED",
                    juxing is None,
                    "expected absent before authorization gate B",
                )
            )
        if candidate_profile is not None and candidate_account_ref is not None:
            conflict = connection.execute(
                "SELECT unit_id,platform FROM execution_unit_platform_bindings "
                "WHERE (unit_id=%s AND platform='kuaishou_juxing') "
                "OR (platform='kuaishou_juxing' AND account_ref=%s) "
                "OR profile_ref=%s",
                (unit_id, candidate_account_ref, str(candidate_profile)),
            ).fetchall()
            checks.append(
                Check(
                    "CANDIDATE_BINDING_NO_CONFLICT",
                    not conflict,
                    f"conflicts={len(conflict)}",
                )
            )
        non_terminal = connection.execute(
            "SELECT count(*) FROM root_tasks WHERE state NOT IN "
            "('COMPLETED','PARTIAL_COMPLETED','FAILED','CANCELLED','EXPIRED','FAILED_VALIDATION')"
        ).fetchone()[0]
        checks.append(Check("NO_IN_FLIGHT_TASKS", int(non_terminal) == 0, f"count={non_terminal}"))
        open_events = connection.execute(
            "SELECT count(*) FROM verification_events WHERE state IN ('OPEN','ACKNOWLEDGED')"
        ).fetchone()[0]
        checks.append(Check("NO_OPEN_VERIFICATION", int(open_events) == 0, f"count={open_events}"))
        takeovers = connection.execute(
            "SELECT count(*) FROM browser_takeover_sessions "
            "WHERE state IN ('REQUESTED','ACTIVE','VERIFYING')"
        ).fetchone()[0]
        checks.append(Check("NO_ACTIVE_TAKEOVER", int(takeovers) == 0, f"count={takeovers}"))
        juxing_tasks = connection.execute(
            "SELECT count(*) FROM root_tasks WHERE platform='kuaishou_juxing'"
        ).fetchone()[0]
        juxing_creators = connection.execute(
            "SELECT count(*) FROM platform_creators WHERE platform='kuaishou_juxing'"
        ).fetchone()[0]
        info["juxing_root_tasks"] = int(juxing_tasks)
        info["juxing_creators"] = int(juxing_creators)
        checks.append(
            Check(
                "NO_JUXING_DATA_BEFORE_SWITCH" if stage != "post_switch" else "JUXING_DATA_PRESENT",
                int(juxing_tasks) == 0 if stage != "post_switch" else int(juxing_tasks) >= 1,
                f"tasks={juxing_tasks} creators={juxing_creators}",
            )
        )
    return checks, info


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - loopback only
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError):
        return None


def runtime_checks(stage: str) -> list[Check]:
    checks: list[Check] = []
    checks.append(
        Check(
            "API_LOOPBACK",
            http_status("http://127.0.0.1:8000/api/auth/me") == 401,
            "GET /api/auth/me -> 401",
            required=stage == "pre_switch",
        )
    )
    checks.append(
        Check(
            "FRONTEND_LOOPBACK",
            http_status("http://127.0.0.1:5173/") == 200,
            "GET / -> 200",
            required=stage == "pre_switch",
        )
    )
    for port, name, required in (
        (57233, "TEMPORAL_57233", stage == "pre_switch"),
        (4192, "ISOLATED_API_4192", False),
        (4193, "ISOLATED_WEB_4193", False),
        (57235, "ISOLATED_TEMPORAL_57235", False),
    ):
        checks.append(Check(name, port_open(port), f"port {port} listening", required=required))
    return checks


def run_preflight(args: argparse.Namespace) -> int:
    runtime_root = Path(args.runtime_root).resolve()
    live_env = load_env_file(Path(args.env_file))
    additions = load_env_file(Path(args.additions_env)) if args.additions_env else {}
    checks = config_checks(
        Path(args.config),
        Path(args.candidate_config) if args.candidate_config else None,
        runtime_root,
        args.unit_id,
        args.expected_account,
    )
    checks.extend(env_checks(live_env, additions, runtime_root))
    candidate_binding = None
    if args.candidate_config:
        from xingtu.runtime import load_unit

        candidate = load_unit(Path(args.candidate_config))
        candidate_binding = _binding_for(candidate, "kuaishou_juxing")
    dsn = _dsn(live_env, args.database_url)
    db, info = db_checks(
        dsn,
        args.unit_id,
        args.stage,
        args.expected_account,
        candidate_binding.profile_directory if candidate_binding else None,
        candidate_binding.account_ref if candidate_binding else None,
    )
    checks.extend(db)
    checks.extend(runtime_checks(args.stage))
    failed = [check for check in checks if check.required and not check.ok]
    report = {
        "schema_version": "juxing_main_preflight.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage": args.stage,
        "unit_id": args.unit_id,
        "checks": [asdict(check) for check in checks],
        "failed_required": [check.name for check in failed],
        "info": info,
    }
    output = Path(args.out).resolve()
    write_private_json(output, report)
    print(
        f"{'PASS' if not failed else 'FAIL'} stage={args.stage} "
        f"checks={len(checks)} failed={len(failed)}"
    )
    for check in checks:
        if not check.ok:
            marker = "FAIL" if check.required else "WARN"
            print(f"  {marker} {check.name}: {check.detail}")
    for check in checks:
        if check.ok and check.name in {
            "DB_MIGRATIONS",
            "UNIT_READY",
            "JUXING_REGISTRY_LIVE",
            "JUXING_PROFILE_LOCK",
            "XINGTU_PROFILE_LOCK",
            "JUXING_SNAPSHOT_PRESENT",
            "EFFECTIVE_JUXING_MAX_TARGET",
        }:
            print(f"  PASS {check.name}: {check.detail}")
    print(f"report: {output}")
    return 0 if not failed else 1


def run_baseline(args: argparse.Namespace) -> int:
    live_env = load_env_file(Path(args.env_file))
    dsn = _dsn(live_env, args.database_url)
    payload = compute_baseline(dsn, args.unit_id)
    write_private_json(Path(args.out).resolve(), payload)
    print(
        f"baseline written: migration={payload['migration_version']} "
        f"xingtu_tasks={len(payload['xingtu_root_task_ids'])} "
        f"xingtu_creators={len(payload['xingtu_creator_ids'])} "
        f"schedule={len(payload['update_schedule_creator_ids'])}"
    )
    print(f"report: {Path(args.out).resolve()}")
    return 0


def run_compare(args: argparse.Namespace) -> int:
    live_env = load_env_file(Path(args.env_file))
    dsn = _dsn(live_env, args.database_url)
    baseline = json.loads(Path(args.baseline).read_text())
    differences = compare_baseline(dsn, baseline)
    report = {
        "schema_version": "juxing_main_compare.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_captured_at": baseline.get("captured_at"),
        "differences": differences,
        "ok": not differences,
    }
    write_private_json(Path(args.out).resolve(), report)
    if differences:
        print(f"FAIL differences={len(differences)}")
        for item in differences:
            print(f"  {item['scope']}: {item['before']} -> {item['after']}")
    else:
        print("PASS star-chart baseline unchanged")
    print(f"report: {Path(args.out).resolve()}")
    return 0 if not differences else 1


async def _session_probe(config_path: Path, runtime_root: Path) -> dict[str, Any]:
    from xingtu.adapter_factory import build_platform_adapter
    from xingtu.contracts import PlatformRegistry
    from xingtu.domain import CollectorError, PlatformId
    from xingtu.runtime import BrowserRuntime, load_unit

    unit = load_unit(config_path)
    active = unit.for_platform(PlatformId.KUAISHOU_JUXING)
    registry = PlatformRegistry.model_validate_json(active.registry_path.read_text())
    registry.require_enabled(live=True)
    runtime = BrowserRuntime(active.model_copy(update={"headless": False}), runtime_root)

    async def guard() -> None:
        return None

    health: Any = None
    error: str | None = None
    async with runtime.open() as browser:
        page = await browser.new_page()
        await page.goto(
            registry.search.entry_url,
            wait_until="domcontentloaded",
            timeout=registry.operation_timeout_seconds * 1000,
        )
        adapter = build_platform_adapter(
            PlatformId.KUAISHOU_JUXING,
            browser,
            registry,
            active.expected_account_id,
            guard,
            on_session_health=lambda _: None,
        )
        try:
            try:
                health = await adapter.inspect_session(page)
            except CollectorError as exc:
                error = exc.code
            else:
                if health.status.value == "VALID":
                    await runtime.export_session_snapshot(browser)
        finally:
            await adapter.close()
    payload: dict[str, Any] = {
        "schema_version": "juxing_main_session_probe.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "unit_id": unit.unit_id,
        "expected_account_id": active.expected_account_id,
        "error": error,
    }
    if health is not None:
        payload["status"] = health.status.value
        payload["evidence_reason"] = health.evidence_reason
        payload["observed_account_id"] = health.observed_account_id
        payload["account_match"] = health.observed_account_id == active.expected_account_id
        payload["protected_page_verified"] = health.protected_page_verified
    return payload


def run_session_check(args: argparse.Namespace) -> int:
    import asyncio

    payload = asyncio.run(_session_probe(Path(args.config), Path(args.runtime_root).resolve()))
    write_private_json(Path(args.out).resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    ok = payload.get("status") == "VALID" and payload.get("account_match") is True
    print(f"{'PASS' if ok else 'FAIL'} juxing session probe")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--unit-id", default=DEFAULT_UNIT)
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)

    baseline = sub.add_parser("baseline", help="write a read-only star-chart content baseline")
    baseline.add_argument("--out", default=str(DEFAULT_OUT / "baseline.json"))
    baseline.set_defaults(func=run_baseline)

    preflight = sub.add_parser("preflight", help="validate the future switch without applying it")
    preflight.add_argument("--config", default=str(DEFAULT_CONFIG))
    preflight.add_argument("--candidate-config", default=None)
    preflight.add_argument("--additions-env", default=None)
    preflight.add_argument("--expected-account", default=DEFAULT_JUXING_ACCOUNT)
    preflight.add_argument("--stage", choices=["pre_switch", "post_switch"], default="pre_switch")
    preflight.add_argument("--out", default=str(DEFAULT_OUT / "preflight.json"))
    preflight.set_defaults(func=run_preflight)

    compare = sub.add_parser("compare", help="recompute the baseline and report differences")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--out", default=str(DEFAULT_OUT / "compare.json"))
    compare.set_defaults(func=run_compare)

    session = sub.add_parser("session-check", help="read-only live juxing session probe")
    session.add_argument("--config", required=True)
    session.add_argument("--out", default=str(DEFAULT_OUT / "session-probe.json"))
    session.set_defaults(func=run_session_check)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
