from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="ProcessProductIntakeV1")
class IntakeWorkflow:
    @workflow.run
    async def run(self, root_task_id: str) -> str:
        # Model retries are owned by P1WorkflowState. Temporal must not multiply that budget.
        result = await workflow.execute_activity(
            "process_intake_v1",
            root_task_id,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=1),
            result_type=str,
        )
        return str(result)
