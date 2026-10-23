"""Unit tests for consumer liveness classification.

The distinction matters because an unsent intake dispatch alone cannot tell "no worker is
running" apart from "the worker is alive but has not polled yet". Temporal keeps disconnected
pollers listed for minutes, so only a fresh ``last_access_time`` proves a live consumer.
"""

from __future__ import annotations

from datetime import timedelta

from xingtu.domain import utcnow
from xingtu.product_queries import ProductQueries
from xingtu.worker_health import (
    DEFAULT_FRESHNESS_SECONDS,
    INTAKE_QUEUE,
    PollerObservation,
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


def test_execution_unit_worker_liveness_is_independent_from_browser_state():
    row = {
        "unit_id": "unit-local",
        "account_ref": "account",
        "line_ref": "local",
        "state": "READY",
        "mode": None,
        "allowed_task_kinds": ["collection"],
        "current_root_task_id": None,
        "browser_stopped": True,
        "lease_until": None,
        "event_state": None,
        "event_reason": None,
        "event_deadline_at": None,
        "takeover_state": None,
        "failure_reason": None,
        "last_heartbeat_at": None,
        "fresh_worker_count": 1,
        "worker_history_count": 1,
        "worker_last_heartbeat_at": utcnow(),
    }
    queries = ProductQueries(None)  # type: ignore[arg-type]
    online = queries._execution_unit_view(row)
    assert online.worker_status == "ONLINE"
    assert online.browser_status == "STOPPED"

    offline = queries._execution_unit_view({**row, "fresh_worker_count": 0})
    assert offline.worker_status == "OFFLINE"
    assert offline.actionable_reason == "COLLECTION_WORKER_OFFLINE"

    duplicate = queries._execution_unit_view({**row, "fresh_worker_count": 2})
    assert duplicate.worker_status == "DUPLICATE"
    assert duplicate.worker_instances == 2
