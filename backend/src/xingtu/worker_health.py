"""Consumer liveness for the P1 intake queue and the per-unit collection queues.

Why this module exists
----------------------
An intake dispatch row (``intake_dispatches.sent=false``) only proves that a dispatch *intent*
exists. It cannot distinguish three very different situations:

1. no consumer process is running at all;
2. a consumer is running but its dispatch loop failed (see ``intake_worker.run_intake_worker``);
3. a consumer is running and the row is simply inside the normal poll window (<= 2 s).

``DescribeTaskQueue`` reports the pollers currently attached to a task queue, but the poller list
is **TTL based, not real time**, and ``last_access_time`` is deliberately coarse:

* after a worker stops, its entry stays visible for minutes (measured > 2 minutes locally);
* while a worker *is* healthy, its long poll holds the request open, so ``last_access_time`` was
  measured as stale for up to **121 s** before refreshing (typical ~58 s).

This module therefore treats the poller signal as a **coarse, supplementary** indicator: it is
useful for an operator or a startup readiness gate, but it is never the sole reason to declare a
task blocked. ``product_queries`` decides that from the precise per-task signal instead: a healthy
dispatch loop flips ``intake_dispatches.sent`` within ~2 s, so an unsent row that has been waiting
for minutes with no recorded dispatch failure means no consumer is processing it.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client

from .domain import utcnow

logger = logging.getLogger(__name__)

# Calibrated to the measured long-poll refresh cadence (observed refresh gaps 58 s, 58 s, 121 s
# for a healthy worker). A smaller value reports live workers as absent.
DEFAULT_FRESHNESS_SECONDS = 180.0
DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_TIMEOUT_SECONDS = 3.0

INTAKE_QUEUE = "xingtu-intake"


def collection_queue(unit_id: str) -> str:
    return f"xingtu-{unit_id}"


@dataclass(frozen=True)
class PollerObservation:
    identity: str
    last_access_at: datetime | None

    @property
    def age_seconds(self) -> float | None:
        if self.last_access_at is None:
            return None
        reference = self.last_access_at
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        return max(0.0, (utcnow() - reference).total_seconds())


@dataclass(frozen=True)
class QueueHealth:
    """Result of one queue liveness observation.

    ``alive`` is deliberately tri-state: ``True`` a fresh consumer was seen, ``False`` the queue
    was observed successfully but no consumer is attached, ``None`` the observation itself failed
    (Temporal unreachable), so callers must not report a definitive fault.
    """

    queue: str
    alive: bool | None
    fresh_pollers: int = 0
    poller_entries: int = 0
    freshest_age_seconds: float | None = None
    checked_at: datetime = field(default_factory=utcnow)
    error: str | None = None

    @property
    def observed(self) -> bool:
        return self.alive is not None


def observe_pollers(
    queue: str,
    pollers: Iterable[PollerObservation],
    *,
    freshness_seconds: float = DEFAULT_FRESHNESS_SECONDS,
) -> QueueHealth:
    """Pure freshness classification; kept separate from transport for unit testing."""
    entries = list(pollers)
    ages = [p.age_seconds for p in entries]
    known = [age for age in ages if age is not None]
    fresh = [age for age in known if age <= freshness_seconds]
    return QueueHealth(
        queue=queue,
        alive=bool(fresh),
        fresh_pollers=len(fresh),
        poller_entries=len(entries),
        freshest_age_seconds=min(known) if known else None,
        checked_at=utcnow(),
    )


def _pollers_from_response(response: Any) -> list[PollerObservation]:
    observations: list[PollerObservation] = []
    for item in response.pollers:
        stamped = item.last_access_time
        observed_at = stamped.ToDatetime(tzinfo=UTC) if stamped and stamped.seconds else None
        observations.append(PollerObservation(identity=item.identity, last_access_at=observed_at))
    return observations


async def describe_queue(client: Client, queue: str) -> QueueHealth:
    response = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace="default", task_queue=TaskQueue(name=queue), report_stats=True
        )
    )
    return observe_pollers(queue, _pollers_from_response(response))


async def check_queues(
    address: str,
    queues: Sequence[str],
    *,
    freshness_seconds: float = DEFAULT_FRESHNESS_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, QueueHealth]:
    """One-shot liveness check for scripts and readiness gates."""

    async def run() -> dict[str, QueueHealth]:
        client = await Client.connect(address)
        results: dict[str, QueueHealth] = {}
        for queue in queues:
            try:
                results[queue] = await asyncio.wait_for(
                    describe_queue(client, queue), timeout=timeout_seconds
                )
            except Exception as exc:  # noqa: BLE001 - liveness must never raise
                logger.warning("queue liveness check failed for %s: %s", queue, type(exc).__name__)
                results[queue] = QueueHealth(
                    queue=queue, alive=None, error=type(exc).__name__, checked_at=utcnow()
                )
        return results

    try:
        return await asyncio.wait_for(run(), timeout=timeout_seconds * (len(queues) + 1) + 5.0)
    except Exception as exc:  # noqa: BLE001
        return {
            queue: QueueHealth(queue=queue, alive=None, error=type(exc).__name__)
            for queue in queues
        }


class WorkerHealthMonitor:
    """Background liveness cache so request handling never talks to Temporal.

    The monitor owns one daemon thread with its own event loop, refreshes every
    ``interval_seconds`` and exposes a lock-protected snapshot. A failure to reach Temporal is
    recorded as ``alive=None`` and never propagated to callers.
    """

    def __init__(
        self,
        address: str,
        queues: Sequence[str],
        *,
        freshness_seconds: float = DEFAULT_FRESHNESS_SECONDS,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.address = address
        self.queues = list(dict.fromkeys(queues))
        self.freshness_seconds = freshness_seconds
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._snapshot: dict[str, QueueHealth] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="xingtu-worker-health", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread:
            thread.join(timeout=timeout)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- observation -------------------------------------------------------------

    def snapshot(self) -> dict[str, QueueHealth]:
        with self._lock:
            return dict(self._snapshot)

    def watch(self, queues: Iterable[str]) -> None:
        """Add queues without restarting the monitor.

        Execution units are database-backed and may appear after API startup. Keeping this list
        dynamic lets the control plane observe each unit's actual collection queue rather than
        inferring Worker liveness from the unit's durable READY state.
        """
        with self._lock:
            self.queues = list(dict.fromkeys([*self.queues, *queues]))

    def queue_health(self, queue: str) -> QueueHealth | None:
        return self.snapshot().get(queue)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            while not self._stop.is_set():
                with self._lock:
                    queues = list(self.queues)
                results = loop.run_until_complete(
                    check_queues(
                        self.address,
                        queues,
                        freshness_seconds=self.freshness_seconds,
                        timeout_seconds=self.timeout_seconds,
                    )
                )
                with self._lock:
                    # Do not erase observations for queues added while this poll was running.
                    self._snapshot.update(results)
                self._stop.wait(self.interval_seconds)
        except Exception as exc:  # noqa: BLE001 - a monitor defect must not kill the API
            logger.warning("worker health monitor stopped: %s", type(exc).__name__)
        finally:
            with self._lock:
                if not self._snapshot:
                    self._snapshot = {
                        queue: QueueHealth(queue=queue, alive=None, error="MONITOR_STOPPED")
                        for queue in self.queues
                    }
            loop.close()

    # -- convenience -------------------------------------------------------------

    def intake_health(self, queue: str = INTAKE_QUEUE) -> QueueHealth | None:
        return self.snapshot().get(queue)

    @staticmethod
    def stale_after(seconds: float) -> timedelta:
        return timedelta(seconds=seconds)
