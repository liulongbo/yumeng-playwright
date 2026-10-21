import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from temporalio.testing import ActivityEnvironment
from xingtu.browser_host import BrowserHost
from xingtu.domain import CollectorError
from xingtu.worker import TemporalHeartbeat, renew_lease


class FakeHost:
    config = SimpleNamespace(is_local_development=True, proxy_server=None)

    def __init__(self, action):
        self.action = action
        self.calls = 0

    def heartbeat_lease(self):
        self.calls += 1
        self.action()


async def test_renew_lease_success():
    host = FakeHost(lambda: None)
    await renew_lease(host, timeout=1)
    assert host.calls == 1


async def test_renew_lease_timeout_becomes_stable_error():
    host = FakeHost(lambda: time.sleep(0.1))
    with pytest.raises(CollectorError) as caught:
        await renew_lease(host, timeout=0.01)
    assert caught.value.code == "RESOURCE_UNAVAILABLE"
    assert caught.value.reason == "HEARTBEAT_TIMEOUT"


async def test_renew_lease_wraps_unexpected_exception():
    def fail():
        raise RuntimeError("database transport closed")

    host = FakeHost(fail)
    with pytest.raises(CollectorError) as caught:
        await renew_lease(host, timeout=1)
    assert caught.value.code == "RESOURCE_UNAVAILABLE"
    assert caught.value.reason == "HEARTBEAT_RuntimeError"


async def test_renew_lease_preserves_lease_error():
    def fail():
        raise CollectorError("LEASE_LOST")

    host = FakeHost(fail)
    with pytest.raises(CollectorError) as caught:
        await renew_lease(host, timeout=1)
    assert caught.value.code == "LEASE_LOST"


async def test_temporal_heartbeat_starts_before_first_interval():
    calls: list[tuple[object, ...]] = []
    threads: list[int] = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *args: (
        calls.append(args),
        threads.append(threading.get_ident()),
    )

    async def body() -> None:
        heartbeat = TemporalHeartbeat("root", interval=0.01)
        heartbeat.start()
        try:
            await asyncio.sleep(0.06)
        finally:
            heartbeat.stop()

    await environment.run(body)
    assert len(calls) >= 2
    assert calls[0] == ("root",)
    # Regression (QA 2026-10-21): the SDK heartbeat must run on the loop thread.  Calling
    # activity.heartbeat directly from the daemon thread raised "no running event loop" and
    # silently disabled every heartbeat for the whole Activity.
    assert set(threads) == {threading.get_ident()}


async def test_temporal_heartbeat_never_calls_the_sdk_from_the_daemon_thread():
    calls: list[tuple[object, ...]] = []
    threads: list[int] = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *args: (
        calls.append(args),
        threads.append(threading.get_ident()),
    )

    async def body() -> None:
        heartbeat = TemporalHeartbeat("root", interval=0.01)
        heartbeat.start()
        try:
            # A synchronous checkpoint transfer blocking the Activity thread.  The daemon thread
            # must queue the heartbeat on the loop instead of calling the SDK itself.
            time.sleep(0.1)
            await asyncio.sleep(0.05)
            assert heartbeat._thread is not None
        finally:
            heartbeat.stop()

    await environment.run(body)
    assert calls
    assert set(threads) == {threading.get_ident()}


def test_temporal_heartbeat_stops_sending_after_stop():
    calls: list[tuple[object, ...]] = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *args: calls.append(args)

    async def body() -> None:
        heartbeat = TemporalHeartbeat("root", interval=0.01)
        heartbeat.start()
        await asyncio.sleep(0.03)
        heartbeat.stop()
        first = len(calls)
        await asyncio.sleep(0.05)
        assert len(calls) == first

    asyncio.run(environment.run(body))
    assert calls


async def test_browser_host_heartbeat_does_not_block_event_loop(monkeypatch):
    async def line_ok(config):
        del config

    monkeypatch.setattr("xingtu.browser_host.ensure_line", line_ok)
    host = SimpleNamespace(
        config=SimpleNamespace(),
        heartbeat_lease=lambda: time.sleep(0.05),
    )
    heartbeat = asyncio.create_task(BrowserHost.heartbeat(host))
    marker = asyncio.Event()

    async def mark() -> None:
        await asyncio.sleep(0.01)
        marker.set()

    marker_task = asyncio.create_task(mark())
    await asyncio.wait_for(marker.wait(), timeout=0.03)
    await heartbeat
    await marker_task


def test_temporal_heartbeat_stops_when_the_event_loop_is_wedged(monkeypatch):
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr("xingtu.worker.activity.heartbeat", lambda *args: calls.append(args))

    async def body() -> None:
        heartbeat = TemporalHeartbeat("root", interval=0.005, loop_watchdog_seconds=0.05)
        heartbeat.start()
        try:
            time.sleep(0.25)  # wedged loop: scheduled callbacks cannot run
            assert heartbeat._thread is not None and not heartbeat._thread.is_alive()
            assert calls == []
        finally:
            heartbeat.stop()

    asyncio.run(body())


async def test_temporal_heartbeat_delivers_after_a_short_loop_block():
    calls: list[tuple[object, ...]] = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *args: calls.append(args)

    async def body() -> None:
        heartbeat = TemporalHeartbeat("root", interval=0.01, loop_watchdog_seconds=5.0)
        heartbeat.start()
        try:
            time.sleep(0.1)  # checkpoint transfer below the watchdog
            await asyncio.sleep(0.05)  # loop drains the queued heartbeat
        finally:
            heartbeat.stop()

    await environment.run(body)
    assert calls


def test_temporal_heartbeat_stops_when_the_activity_token_is_gone(monkeypatch):
    calls: list[tuple[object, ...]] = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *args: calls.append(args)

    def fail(*args):
        raise RuntimeError("activity token not found")

    monkeypatch.setattr("xingtu.worker.activity.heartbeat", fail)

    async def body() -> None:
        heartbeat = TemporalHeartbeat("root", interval=0.01)
        heartbeat.start()
        await asyncio.sleep(0.1)
        assert heartbeat._thread is not None and not heartbeat._thread.is_alive()
        heartbeat.stop()

    asyncio.run(environment.run(body))
    assert calls == []


def test_temporal_heartbeat_threads_do_not_accumulate():
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *args: None

    async def body() -> None:
        for _ in range(20):
            heartbeat = TemporalHeartbeat("root", interval=0.01)
            heartbeat.start()
            await asyncio.sleep(0.005)
            heartbeat.stop()

    asyncio.run(environment.run(body))
    assert not any(
        thread.name == "temporal-activity-heartbeat" and thread.is_alive()
        for thread in threading.enumerate()
    )


async def test_temporal_heartbeat_stops_when_the_activity_is_cancelled():
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *args: None
    started = asyncio.Event()

    async def body() -> None:
        heartbeat = TemporalHeartbeat("root", interval=0.01)
        heartbeat.start()
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            heartbeat.stop()

    task = asyncio.create_task(environment.run(body))
    await asyncio.wait_for(started.wait(), timeout=2)
    environment.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any(
        thread.name == "temporal-activity-heartbeat" and thread.is_alive()
        for thread in threading.enumerate()
    )


async def test_collect_starts_and_stops_the_heartbeat_thread(monkeypatch):
    events: list[object] = []

    class FakeHeartbeat:
        def __init__(self, root, **kwargs):
            events.append(("init", root))

        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

    monkeypatch.setattr("xingtu.worker.TemporalHeartbeat", FakeHeartbeat)
    from pathlib import Path
    from types import SimpleNamespace

    from xingtu.worker import Activities

    activities = Activities(SimpleNamespace(), SimpleNamespace(), Path("."))

    async def complete(root):
        events.append(("collect", root))
        return "COMPLETED"

    monkeypatch.setattr(activities, "_collect", complete)
    assert await activities.collect("root") == "COMPLETED"
    assert events == [("init", "root"), "start", ("collect", "root"), "stop"]


async def test_collect_stops_the_heartbeat_thread_on_failure(monkeypatch):
    events: list[str] = []

    class FakeHeartbeat:
        def __init__(self, root, **kwargs):
            pass

        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

    monkeypatch.setattr("xingtu.worker.TemporalHeartbeat", FakeHeartbeat)
    from pathlib import Path
    from types import SimpleNamespace

    from xingtu.worker import Activities

    activities = Activities(SimpleNamespace(), SimpleNamespace(), Path("."))

    async def fail(root):
        raise RuntimeError("boom")

    monkeypatch.setattr(activities, "_collect", fail)
    with pytest.raises(RuntimeError, match="boom"):
        await activities.collect("root")
    assert events == ["start", "stop"]
