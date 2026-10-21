"""Repeatable old-vs-new checkpoint hot-path benchmark over a throttled TCP proxy.

This is an isolated benchmark, not a real collection:

* PostgreSQL runs in a local disposable container (never production).
* A separate process proxies the Worker's PostgreSQL connection and applies the measured
  production shape: ~100 KiB/s cloud -> Mac, fast Mac -> cloud, plus 10 ms one-way latency.
* The Engine is the real code from the selected source tree (old baseline or current worktree).
* The adapter is a no-op so the measured time is database/transport, not browser work.

It reports full-checkpoint transfers, bytes on the wire, cumulative DB wait, event-loop lag,
Temporal heartbeat timestamps and the resulting checkpoint size.  Run it once per source/size.

Example:
    PYTHONPATH="$PWD/backend/src" .venv/bin/python scripts/diag/checkpoint_benchmark.py \\
        --label new --target-bytes 524288 --output /tmp/new-0.5.json
    PYTHONPATH="$PWD/.runtime/perf/old_src" .venv/bin/python ... --label old ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import sys
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
try:  # the caller selects old/current with PYTHONPATH; fall back to this checkout
    import xingtu  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT / "backend" / "src"))

from temporalio.testing import ActivityEnvironment  # noqa: E402
from xingtu import worker as worker_module  # noqa: E402
from xingtu.domain import (  # noqa: E402
    Candidate,
    CandidateDiagnostic,
    CreatorRef,
    ExecutionContext,
    FieldObservation,
    FieldStatus,
    Filter,
    FilterPlan,
    ModuleObservation,
    SegmentBudget,
    uid,
)
from xingtu.engine import Engine  # noqa: E402
from xingtu.repository import Repository  # noqa: E402

DB_BASE = os.environ.get(
    "XINGTU_BENCH_DATABASE_URL", "postgresql://postgres:bench@127.0.0.1:55439/xingtu_test_perfbench"
)
PROXY_LISTEN = 55440
PROXY_TARGET = 55439


class TokenBucket:
    def __init__(self, rate_bytes_per_second: float):
        self.rate = rate_bytes_per_second
        self.capacity = max(rate_bytes_per_second * 0.2, 65536)
        self.tokens = self.capacity
        self.last = time.monotonic()

    async def consume(self, amount: int) -> None:
        while True:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= amount:
                self.tokens -= amount
                return
            await asyncio.sleep((amount - self.tokens) / self.rate)


def proxy_process_main(
    listen_port: int,
    target_port: int,
    down_rate: float,
    up_rate: float,
    down_bytes: Any,
    up_bytes: Any,
    ready: Any,
    stop: Any,
) -> None:
    down_bucket, up_bucket = TokenBucket(down_rate), TokenBucket(up_rate)
    latency = 0.001

    async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, bucket, counter):
        try:
            while True:
                data = await reader.read(16384)
                if not data:
                    break
                await bucket.consume(len(data))
                if latency:
                    await asyncio.sleep(latency)
                writer.write(data)
                await writer.drain()
                with counter.get_lock():
                    counter.value += len(data)
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def handle(reader, writer):
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", target_port)
        await asyncio.gather(
            pipe(reader, up_writer, up_bucket, up_bytes),
            pipe(up_reader, writer, down_bucket, down_bytes),
        )

    async def run():
        server = await asyncio.start_server(handle, "127.0.0.1", listen_port)
        ready.set()
        while not stop.is_set():
            await asyncio.sleep(0.05)
        server.close()
        await server.wait_closed()

    asyncio.run(run())


class FastAdapter:
    """No browser work: configurable modules/fields, no featured collections."""

    featured_keys: list[str] = []
    operation_metrics: dict[str, int] = {}

    def __init__(self, module_keys: list[str], field_keys: dict[str, list[str]]):
        self.module_keys = module_keys
        self.module_fields = field_keys
        self.module_checkpoint_versions = {key: 1 for key in module_keys}

    @asynccontextmanager
    async def profile(self, creator, ctx):
        yield

    async def collect_module(self, key, creator, ctx, row_covers=None):
        operation = uid()
        fields = []
        for field_key in self.module_fields[key]:
            if field_key == "platform_creator_id":
                value = creator.platform_creator_id
            elif field_key == "nickname":
                value = "bench"
            else:
                value = "v" * 40
            fields.append(
                FieldObservation(
                    field_key=field_key,
                    value=value,
                    raw_value=value,
                    status=FieldStatus.COLLECTED,
                    source_kind="dom",
                    source_contract=ctx.contract_version,
                    operation_id=operation,
                    session_version=ctx.session_version,
                )
            )
        return ModuleObservation(
            creator_ref=creator,
            module_key=key,
            fields=fields,
            expected_fields=list(self.module_fields[key]),
            operation_id=operation,
            contract_version=ctx.contract_version,
        )

    async def close(self) -> None:
        return None


class TimedRepository(Repository):
    def __init__(self, dsn: str):
        super().__init__(dsn)
        self.calls: list[tuple[str, float]] = []
        self.gets = self.edits = self.progress = 0

    def reset(self) -> None:
        self.calls.clear()
        self.gets = self.edits = self.progress = 0

    def get(self, root):
        started = time.monotonic()
        self.gets += 1
        try:
            return super().get(root)
        finally:
            self.calls.append(("get", time.monotonic() - started))

    @contextmanager
    def edit(self, root, ctx=None, *, require_lease=True):
        started = time.monotonic()
        self.edits += 1
        try:
            with super().edit(root, ctx, require_lease=require_lease) as value:
                yield value
        finally:
            self.calls.append(("edit", time.monotonic() - started))

    def record_progress(self, *args, **kwargs):
        if not hasattr(super(), "record_progress"):
            raise AttributeError("record_progress is unavailable in the old source tree")
        started = time.monotonic()
        self.progress += 1
        try:
            return super().record_progress(*args, **kwargs)
        finally:
            self.calls.append(("progress", time.monotonic() - started))


def seed_task(
    direct_dsn: str,
    target_bytes: int,
    module_keys: list[str],
    field_keys: dict[str, list[str]],
):
    repo = Repository(direct_dsn)
    repo.register_unit("unit", "acct", "line", "/tmp/profile", "local_development")
    with repo.connect() as conn:
        conn.execute(
            "UPDATE execution_units SET state='READY',session_version=1,browser_stopped=true"
        )
    plan = FilterPlan(
        capability_version="bench-v1",
        target_count=1,
        filters=[Filter(field="keyword", operator="eq", value="bench", source_fields=["keyword"])],
    )
    root = repo.create(
        plan,
        "unit",
        uid(),
        "bench",
        adapter_version="bench-v1",
        contract_version="bench-v1",
        modules=module_keys,
    )
    task = repo.get(root)
    generation, session = repo.acquire("unit", task.attempt_id)
    # Isolated benchmark: extend the lease so the old path can be measured at 2.5 MB.  The real
    # old path exceeds the 120 s lease TTL at this size and fails with LEASE_LOST (recorded in the
    # verification report); extending here isolates the DB/transport cost for comparison.
    with repo.connect() as conn:
        conn.execute(
            "UPDATE execution_units SET lease_until=now()+interval '2 hours' WHERE unit_id='unit'"
        )
    ref = CreatorRef(
        platform_creator_id="creator-1",
        verified_homepage="https://synthetic.invalid/creator/1",
    )
    with repo.edit(root) as (current, _):
        current.checkpoint.candidates.append(Candidate(ref=ref, valid=True, state="pending"))
        current.valid_count = 1
        current.checkpoint.profile_field_keys = field_keys
    actual = _checkpoint_text_bytes(repo, root)
    padding = max(0, target_bytes - actual - 512)
    with repo.edit(root) as (current, _):
        current.checkpoint.diagnostics.append(
            CandidateDiagnostic(
                reason="UNVERIFIED_HOMEPAGE",
                detail="x" * padding,
                source_ref="bench",
                operation_id=uid(),
            )
        )
    actual = _checkpoint_text_bytes(repo, root)
    if actual < target_bytes:
        with repo.edit(root) as (current, _):
            current.checkpoint.diagnostics[-1].detail += "x" * (target_bytes - actual)
        actual = _checkpoint_text_bytes(repo, root)
    ctx = ExecutionContext(
        root_task_id=root,
        task_id=task.task_id,
        attempt_id=task.attempt_id,
        execution_unit_id="unit",
        lease_generation=generation,
        session_version=session,
        capability_version="bench-v1",
        adapter_version="bench-v1",
        contract_version="bench-v1",
        network_mode="local_development",
        budget=SegmentBudget(),
    )
    return repo, root, ctx, actual


def _checkpoint_text_bytes(repo: Repository, root: str) -> int:
    task = repo.get(root)
    return len(json.dumps(task.checkpoint.model_dump(mode="json"), ensure_ascii=False).encode())


async def monitor_loop_lag(stop: asyncio.Event, lags: list[float]) -> None:
    previous = asyncio.get_running_loop().time()
    while not stop.is_set():
        await asyncio.sleep(0.01)
        now = asyncio.get_running_loop().time()
        lags.append(max(0.0, now - previous - 0.01))
        previous = now


async def run_engine(engine: Engine, root: str, heartbeats: list[float]) -> None:
    heartbeat_cls = getattr(worker_module, "TemporalHeartbeat", None)
    if heartbeat_cls is None:
        await engine._collect_once("creator-1")
        return
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *args: heartbeats.append(time.monotonic())

    async def body() -> None:
        heartbeat = heartbeat_cls("bench", interval=1.0)
        heartbeat.start()
        try:
            await engine._collect_once("creator-1")
        finally:
            heartbeat.stop()

    await environment.run(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--target-bytes", type=int, required=True)
    parser.add_argument("--rate-kib", type=float, default=100.0)
    parser.add_argument("--modules", type=int, default=1)
    parser.add_argument("--observation-fields", type=int, default=100)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    mp_context = mp.get_context("spawn")
    down_bytes = mp_context.Value("Q", 0)
    up_bytes = mp_context.Value("Q", 0)
    ready = mp_context.Event()
    stop = mp_context.Event()
    proxy = mp_context.Process(
        target=proxy_process_main,
        args=(
            PROXY_LISTEN,
            PROXY_TARGET,
            args.rate_kib * 1024,
            max(2 * 1024 * 1024, min(8 * 1024 * 1024, args.rate_kib * 1024 * 10)),
            down_bytes,
            up_bytes,
            ready,
            stop,
        ),
        daemon=True,
    )
    proxy.start()
    if not ready.wait(15):
        raise SystemExit("proxy did not become ready")

    schema = "bench_" + uid().replace("-", "")[:12]
    with psycopg.connect(DB_BASE, row_factory=dict_row) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    direct_dsn = make_conninfo(DB_BASE, options=f"-csearch_path={schema}")
    proxy_dsn = make_conninfo(DB_BASE, port=PROXY_LISTEN, options=f"-csearch_path={schema}")
    direct_repo = Repository(direct_dsn)
    direct_repo.migrate(ROOT / "migrations")
    module_keys = ["basic"] + [f"m{i}" for i in range(2, max(1, args.modules) + 1)]
    field_keys = {
        key: (
            ["platform_creator_id", "nickname"]
            + [f"basic_f{i}" for i in range(args.observation_fields)]
            if key == "basic"
            else [f"{key}_f{i}" for i in range(args.observation_fields)]
        )
        for key in module_keys
    }
    try:
        repo, root, ctx, checkpoint_bytes = seed_task(
            direct_dsn, args.target_bytes, module_keys, field_keys
        )
        timed_repo = TimedRepository(proxy_dsn)
        engine = Engine(timed_repo, FastAdapter(module_keys, field_keys), ctx)
        heartbeats: list[float] = []
        lags: list[float] = []

        async def scenario():
            timed_repo.reset()
            with down_bytes.get_lock():
                down_bytes.value = 0
            with up_bytes.get_lock():
                up_bytes.value = 0
            lag_stop = asyncio.Event()
            lag_task = asyncio.create_task(monitor_loop_lag(lag_stop, lags))
            await asyncio.sleep(0.02)  # let the monitor take its first sample
            started = time.monotonic()
            try:
                await run_engine(engine, root, heartbeats)
            finally:
                elapsed = time.monotonic() - started
                lag_stop.set()
                await lag_task
            return elapsed

        elapsed = asyncio.run(scenario())
        final = direct_repo.get(root)
        gaps = [b - a for a, b in zip(heartbeats, heartbeats[1:], strict=False)]
        result = {
            "label": args.label,
            "source_path": __import__("xingtu").__file__,
            "target_checkpoint_bytes": args.target_bytes,
            "checkpoint_text_bytes": checkpoint_bytes,
            "final_checkpoint_text_bytes": len(
                json.dumps(final.checkpoint.model_dump(mode="json"), ensure_ascii=False).encode()
            ),
            "modules": args.modules,
            "rate_kib": args.rate_kib,
            "lease_ttl_extended": True,
            "elapsed_s": round(elapsed, 3),
            "db_wait_s": round(sum(value for _, value in timed_repo.calls), 3),
            "max_single_db_call_s": round(
                max((value for _, value in timed_repo.calls), default=0.0), 3
            ),
            "get_calls": timed_repo.gets,
            "edit_calls": timed_repo.edits,
            "progress_calls": timed_repo.progress,
            "full_checkpoint_transfers": timed_repo.gets + timed_repo.edits,
            "proxy_down_bytes": down_bytes.value,
            "proxy_up_bytes": up_bytes.value,
            "loop_lag_max_s": round(max(lags) if lags else 0.0, 3),
            "loop_lag_over_1s": sum(1 for value in lags if value > 1.0),
            "heartbeat_count": len(heartbeats),
            "heartbeat_max_gap_s": round(max(gaps) if gaps else 0.0, 3),
            "heartbeat_gaps_s": [round(value, 3) for value in gaps],
            "module_seconds": final.checkpoint.module_seconds,
            "calls": [(name, round(value, 3)) for name, value in timed_repo.calls],
        }
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop.set()
        proxy.join(timeout=10)
        with psycopg.connect(DB_BASE) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    raise SystemExit(main())
