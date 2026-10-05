from datetime import timedelta
from functools import partial

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="CollectF04F05V1")
class CollectionWorkflow:
    def __init__(self) -> None:
        self.revision = 0

    @workflow.signal
    def wake(self) -> None:
        self.revision += 1

    def changed(self, revision: int) -> bool:
        return self.revision != revision

    @workflow.run
    async def run(self, root_task_id: str) -> str:
        # History carries only IDs/state; no browser objects, database I/O or candidate bodies.
        while True:
            revision = self.revision
            state = await workflow.execute_activity(
                "collect_segment_v1",
                root_task_id,
                start_to_close_timeout=timedelta(minutes=125),
                heartbeat_timeout=timedelta(seconds=45),
                retry_policy=RetryPolicy(
                    maximum_attempts=4,
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2,
                    maximum_interval=timedelta(seconds=60),
                ),
                result_type=str,
            )
            if state in {
                "CANCELLED",
                "COMPLETED",
                "PARTIAL_COMPLETED",
                "FAILED",
                "FAILED_VALIDATION",
            }:
                return str(state)
            wait_for_explicit_login = state in {
                "WAITING_FOR_LOGIN",
                "WAITING_FOR_ACCOUNT",
            } and workflow.patched("waiting-for-login-explicit-wake-v1")
            if state == "PAUSED_BUDGET" or wait_for_explicit_login:
                # Login/challenge maintenance is user-driven.  A timeout must not poll every 30
                # seconds and repeatedly launch visible Chrome processes; `xingtu login` records
                # the durable dispatch intent that sends this wake. `patched` preserves replay
                # compatibility with histories that already contain the former 30-second timer.
                await workflow.wait_condition(partial(self.changed, revision))
            else:
                try:
                    await workflow.wait_condition(
                        partial(self.changed, revision),
                        timeout=timedelta(seconds=30),
                    )
                except TimeoutError:
                    pass
            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(root_task_id)
