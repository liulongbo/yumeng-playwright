from pathlib import Path

import httpx
import pytest
from xingtu.contracts import PlatformRegistry
from xingtu.intake import DeepSeekAdapter, IntakeGraph, LLMResult
from xingtu.product_models import ModelUsage, P1WorkflowState, RequirementForm


def live_capabilities():
    return PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    ).capabilities


def initial_state():
    return P1WorkflowState(
        root_task_id="root",
        requirement_id="requirement",
        p1_task_id="p1",
        requirement_form=RequirementForm(keyword="宠物", target_count=20),
        capability_version=live_capabilities().version,
        capability_snapshot_ref="registry:test",
        model_config_id="deepseek-flash",
    )


class MemoryRuns:
    def __init__(self):
        self.rows = {}

    def existing_model_run(self, root_task_id, retry_cycle, attempt):
        return self.rows.get((root_task_id, retry_cycle, attempt))

    def begin_model_run(self, state, *, provider, requested_model, input_digest):
        run_id = f"run-{state.attempt_count}"
        self.rows[(state.root_task_id, state.retry_cycle, state.attempt_count)] = {
            "model_run_id": run_id,
            "status": "started",
            "provider": provider,
            "requested_model": requested_model,
            "input_digest": input_digest,
        }
        return run_id

    def finish_model_run(self, model_run_id, **values):
        row = next(row for row in self.rows.values() if row["model_run_id"] == model_run_id)
        row.update(values)


class SequenceAdapter:
    provider = "test"
    model = "test-model"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    async def generate_filter_plan(self, **kwargs):
        del kwargs
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return LLMResult(payload=payload, response_model=self.model)


def expected_payload(target=20, *, keyword="宠物"):
    return {
        "schema_version": "filter_plan.v1",
        "platform": "douyin_xingtu",
        "capability_version": live_capabilities().version,
        "target_count": target,
        "filters": [
            {
                "field": "keyword",
                "operator": "eq",
                "value": keyword,
                "source_fields": ["keyword"],
                "unit": None,
                "currency": None,
                "cooperation_form": None,
            }
        ],
        "sort": {"key": "score"},
        "validation_errors": [],
    }


async def test_state_graph_accepts_only_exact_plan():
    adapter = SequenceAdapter([expected_payload()])
    runs = MemoryRuns()
    result = await IntakeGraph(live_capabilities(), adapter, runs).run(initial_state())
    assert result.outcome == "succeeded"
    assert result.final_plan and result.final_plan.target_count == 20
    assert result.attempt_count == 1
    assert adapter.calls == 1
    assert len(result.model_run_ids) == 1


@pytest.mark.parametrize(
    "bad_payload",
    [
        expected_payload(target=21),
        expected_payload(keyword="宠物达人"),
        {**expected_payload(), "extra": "invented"},
    ],
)
async def test_model_cannot_change_or_add_user_fields_and_stops_at_three(bad_payload):
    adapter = SequenceAdapter([bad_payload])
    result = await IntakeGraph(live_capabilities(), adapter, MemoryRuns()).run(initial_state())
    assert result.outcome == "failed_validation"
    assert result.final_plan is None
    assert result.attempt_count == 3
    assert adapter.calls == 3
    assert result.final_error


async def test_repair_path_can_recover_on_second_attempt():
    adapter = SequenceAdapter([expected_payload(target=21), expected_payload()])
    result = await IntakeGraph(live_capabilities(), adapter, MemoryRuns()).run(initial_state())
    assert result.outcome == "succeeded"
    assert result.attempt_count == 2
    assert adapter.calls == 2


async def test_deepseek_adapter_uses_responses_json_schema_and_parses_usage():
    async def handler(request):
        sent = request.read()
        assert b'"reasoning":{"effort":"none"}' in sent
        assert b'"type":"json_schema"' in sent
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "deepseek-flash-actual",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "{}"},
                        ],
                    }
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DeepSeekAdapter("secret", client=client).generate_filter_plan(
            form=RequirementForm(keyword="宠物"),
            capabilities=live_capabilities(),
            expected_constraints=expected_payload(),
            prompt_version="v1",
            repair_errors=[],
        )
    assert result.payload == {}
    assert result.response_model == "deepseek-flash-actual"
    assert result.usage == ModelUsage(input_tokens=11, output_tokens=7)


async def test_deepseek_startup_verifies_configured_model():
    async def handler(request):
        assert request.url.path == "/models"
        return httpx.Response(200, json={"data": [{"id": "deepseek-flash"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await DeepSeekAdapter("secret", client=client).verify_model()
