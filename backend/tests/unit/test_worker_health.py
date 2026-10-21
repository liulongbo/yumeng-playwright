"""Unit tests for consumer liveness classification.

The distinction matters because an unsent intake dispatch alone cannot tell "no worker is
running" apart from "the worker is alive but has not polled yet". Temporal keeps disconnected
pollers listed for minutes, so only a fresh ``last_access_time`` proves a live consumer.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from xingtu.domain import utcnow
from xingtu.product_queries import ProductQueries
from xingtu.worker_health import (
    DEFAULT_FRESHNESS_SECONDS,
    INTAKE_QUEUE,
    PollerObservation,
    QueueHealth,
    WorkerHealthMonitor,
    collection_queue,
    observe_pollers,
)


def poller(age_seconds: float | None, identity: str = "worker@host") -> PollerObservation:
    return PollerObservation(
        identity=identity,
        last_access_at=None if age_seconds is None else utcnow() - timedelta(seconds=age_seconds),
    )


def test_no_pollers_is_a_confirmed_absence():
    health = observe_pollers(INTAKE_QUEUE, [])
    assert health.alive is False
    assert health.observed is True
    assert health.fresh_pollers == 0
    assert health.poller_entries == 0
    assert health.freshest_age_seconds is None


def test_fresh_poller_is_a_live_consumer():
    health = observe_pollers(INTAKE_QUEUE, [poller(0.4)])
    assert health.alive is True
    assert health.fresh_pollers == 1
    assert health.freshest_age_seconds is not None
    assert health.freshest_age_seconds < DEFAULT_FRESHNESS_SECONDS


def test_a_healthy_worker_may_look_stale_without_being_dead():
    """Measured long-poll behaviour: a live worker's poller age reached 121 s before refreshing.

    The threshold must tolerate that, otherwise readiness and health reporting produce false
    negatives for a perfectly healthy consumer.
    """
    health = observe_pollers(INTAKE_QUEUE, [poller(121.0)])
    assert health.alive is True
    assert health.freshest_age_seconds is not None
    assert health.freshest_age_seconds < DEFAULT_FRESHNESS_SECONDS


def test_long_abandoned_poller_is_not_a_live_consumer():
    """A dead worker's entry keeps ageing well beyond any refresh cadence."""
    health = observe_pollers(INTAKE_QUEUE, [poller(400.0), poller(300.0)])
    assert health.alive is False
    assert health.poller_entries == 2
    assert health.fresh_pollers == 0
    assert health.freshest_age_seconds is not None
    assert health.freshest_age_seconds > DEFAULT_FRESHNESS_SECONDS


def test_mixed_entries_are_alive_when_any_poller_is_fresh():
    health = observe_pollers(INTAKE_QUEUE, [poller(400.0), poller(0.1, identity="new@host")])
    assert health.alive is True
    assert health.fresh_pollers == 1
    assert health.poller_entries == 2


def test_poller_without_timestamp_does_not_count_as_fresh():
    health = observe_pollers(INTAKE_QUEUE, [poller(None)])
    assert health.alive is False
    assert health.poller_entries == 1
    assert health.freshest_age_seconds is None


def test_queue_health_is_unobserved_when_transport_failed():
    from xingtu.worker_health import QueueHealth

    health = QueueHealth(queue=INTAKE_QUEUE, alive=None, error="TemporalUnreachable")
    assert health.observed is False
    assert health.alive is None


def test_collection_queue_name_is_derived_from_unit():
    assert collection_queue("unit-local-mac-02") == "xingtu-unit-local-mac-02"


def test_monitor_can_watch_new_collection_queues_without_duplicates():
    monitor = WorkerHealthMonitor("temporal:7233", [INTAKE_QUEUE])
    monitor.watch([collection_queue("unit-mac-cell-01"), INTAKE_QUEUE])

    assert monitor.queues == [INTAKE_QUEUE, "xingtu-unit-mac-cell-01"]


def unit_row(state: str = "READY") -> dict[str, object]:
    return {
        "unit_id": "unit-mac-cell-01",
        "account_ref": "account-secret-ref",
        "line_ref": "cell-01",
        "state": state,
        "mode": None,
        "allowed_task_kinds": ["collection"],
        "current_root_task_id": None,
        "browser_stopped": True,
        "owner": None,
        "lease_until": None,
        "network_mode": "production_line",
        "event_deadline_at": None,
        "event_state": None,
        "takeover_state": None,
        "last_heartbeat_at": None,
        "event_reason": None,
        "failure_reason": None,
    }


def test_ready_database_state_is_not_reported_available_without_live_worker():
    monitor = SimpleNamespace(
        queue_health=lambda queue: QueueHealth(queue=queue, alive=False),
    )
    queries = ProductQueries(SimpleNamespace(), monitor)  # type: ignore[arg-type]

    view = queries._execution_unit_view(unit_row())

    assert view.worker_status == "OFFLINE"
    assert view.unit_availability == "UNAVAILABLE"
    assert view.line_health == "UNKNOWN"


def test_live_worker_and_ready_unit_are_reported_separately():
    monitor = SimpleNamespace(
        queue_health=lambda queue: QueueHealth(queue=queue, alive=True, fresh_pollers=1),
    )
    queries = ProductQueries(SimpleNamespace(), monitor)  # type: ignore[arg-type]

    view = queries._execution_unit_view(unit_row())

    assert view.worker_status == "ONLINE"
    assert view.unit_availability == "AVAILABLE"
    assert view.browser_lease_status == "IDLE"
