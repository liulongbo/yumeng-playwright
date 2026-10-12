from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

import httpx
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from .domain import Capabilities, CollectorError, Filter, FilterPlan, NumberRange, Sort
from .product_models import (
    FieldError,
    LLMResult,
    ModelUsage,
    P1WorkflowState,
    RequirementForm,
)


class LLMFailure(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool, indeterminate: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.indeterminate = indeterminate
        super().__init__(f"{code}: {message}")


class LLMAdapter(Protocol):
    provider: str
    model: str

    async def generate_filter_plan(
        self,
        *,
        form: RequirementForm,
        capabilities: Capabilities,
        expected_constraints: dict[str, Any],
        prompt_version: str,
        repair_errors: list[FieldError],
    ) -> LLMResult: ...


class ModelRunStore(Protocol):
    def existing_model_run(
        self, root_task_id: str, retry_cycle: int, attempt: int
    ) -> dict[str, Any] | None: ...

    def begin_model_run(
        self,
        state: P1WorkflowState,
        *,
        provider: str,
        requested_model: str,
        input_digest: str,
    ) -> str: ...

    def finish_model_run(
        self,
        model_run_id: str,
        *,
        status: str,
        response_model: str | None = None,
        output_payload: dict[str, Any] | None = None,
        error_payload: dict[str, Any] | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        delivery_status: str = "received",
    ) -> None: ...


class DeepSeekAdapter:
    provider = "deepseek"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "deepseek-flash",
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 90,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeek API key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def verify_model(self) -> None:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.get(
                self.base_url + "/models",
                headers={"Authorization": "Bearer " + self.api_key},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LLMFailure("AI_TRANSPORT_ERROR", type(exc).__name__, retryable=True) from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code != 200:
            raise LLMFailure(
                "AI_MODEL_CHECK_FAILED",
                f"provider status {response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            models = response.json().get("data", [])
        except (ValueError, AttributeError) as exc:
            raise LLMFailure(
                "AI_MODEL_CHECK_FAILED", "invalid models response", retryable=True
            ) from exc
        if self.model not in {item.get("id") for item in models if isinstance(item, dict)}:
            raise LLMFailure("AI_MODEL_UNAVAILABLE", self.model, retryable=False)

    async def generate_filter_plan(
        self,
        *,
        form: RequirementForm,
        capabilities: Capabilities,
        expected_constraints: dict[str, Any],
        prompt_version: str,
        repair_errors: list[FieldError],
    ) -> LLMResult:
        # Only the requirement and public capability dictionary cross the provider boundary.
        request_body = {
            "model": self.model,
            "instructions": (
                "Return one JSON FilterPlan matching the supplied JSON Schema. Preserve every "
                "user value exactly. Do not add, omit, infer, translate, broaden, or narrow any "
                "filter. The deterministic constraints are authoritative. Output JSON only. "
                f"Prompt version: {prompt_version}."
            ),
            "input": json.dumps(
                {
                    "requirement_form": form.model_dump(mode="json"),
                    "capabilities": capabilities.model_dump(mode="json"),
                    "expected_constraints": expected_constraints,
                    "repair_errors": [error.model_dump(mode="json") for error in repair_errors],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            "reasoning": {"effort": "none"},
            "temperature": 0,
            "max_output_tokens": 2000,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "filter_plan_v1",
                    "schema": FilterPlan.model_json_schema(),
                }
            },
            "tool_choice": "none",
        }
        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(
                self.base_url + "/responses", headers=headers, json=request_body
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LLMFailure(
                "AI_TRANSPORT_ERROR", type(exc).__name__, retryable=True, indeterminate=True
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code in {401, 402, 403}:
            raise LLMFailure("AI_AUTH_OR_QUOTA", "provider rejected credentials", retryable=False)
        if response.status_code == 429 or response.status_code >= 500:
            raise LLMFailure(
                "AI_PROVIDER_RETRYABLE",
                f"provider status {response.status_code}",
                retryable=True,
            )
        if response.status_code >= 400:
            raise LLMFailure(
                "AI_PROVIDER_REJECTED", f"provider status {response.status_code}", retryable=False
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMFailure(
                "AI_INVALID_RESPONSE", "response was not JSON", retryable=True
            ) from exc
        if body.get("status") != "completed":
            reason = (body.get("error") or {}).get("code") or body.get("status") or "unknown"
            retryable = body.get("status") == "incomplete"
            raise LLMFailure("AI_INCOMPLETE_RESPONSE", str(reason), retryable=retryable)
        output_texts = [
            part.get("text")
            for item in body.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text" and isinstance(part.get("text"), str)
        ]
        if len(output_texts) != 1 or not output_texts[0].strip():
            raise LLMFailure("AI_EMPTY_OUTPUT", "one output_text item required", retryable=True)
        try:
            payload = json.loads(output_texts[0])
        except json.JSONDecodeError as exc:
            raise LLMFailure("AI_INVALID_JSON", "output_text was not JSON", retryable=True) from exc
        if not isinstance(payload, dict):
            raise LLMFailure("AI_INVALID_JSON", "JSON object required", retryable=True)
        usage = body.get("usage") or {}
        return LLMResult(
            payload=payload,
            response_model=body.get("model"),
            usage=ModelUsage(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            ),
        )


def build_expected_plan(form: RequirementForm, capabilities: Capabilities) -> FilterPlan:
    """Map values mechanically. The LLM is never allowed to invent this truth."""
    normalized = form.normalized()
    filters: list[Filter] = []
    if normalized.keyword is not None:
        filters.append(
            Filter(
                field="keyword",
                operator="eq",
                value=normalized.keyword,
                source_fields=["keyword"],
            )
        )
    if normalized.creator_types:
        filters.append(
            Filter(
                field="creator_type",
                operator="in",
                value=normalized.creator_types,
                source_fields=["creator_types"],
            )
        )
    if normalized.followers is not None:
        filters.append(
            Filter(
                field="followers",
                operator="range",
                value=NumberRange(min=normalized.followers.min, max=normalized.followers.max),
                source_fields=["followers.min", "followers.max"],
                unit=normalized.followers.unit,
            )
        )
    if normalized.creator_gender is not None:
        filters.append(
            Filter(
                field="gender",
                operator="eq",
                value=normalized.creator_gender,
                source_fields=["creator_gender"],
            )
        )
    if normalized.creator_regions:
        filters.append(
            Filter(
                field="region",
                operator="in",
                value=normalized.creator_regions,
                source_fields=["creator_regions"],
            )
        )
    if normalized.quote is not None:
        filters.append(
            Filter(
                field="quote",
                operator="range",
                value=NumberRange(min=normalized.quote.min, max=normalized.quote.max),
                source_fields=["quote.min", "quote.max"],
                unit=normalized.quote.unit,
                currency=normalized.quote.currency,
                cooperation_form=normalized.quote.cooperation_form,
            )
        )
    sort_key = normalized.sort_key or (
        capabilities.sorts[0] if len(capabilities.sorts) == 1 else ""
    )
    plan = FilterPlan(
        capability_version=capabilities.version,
        target_count=normalized.target_count,
        filters=filters,
        sort=Sort(key=sort_key),
    )
    capabilities.validate_plan(plan, live=True)
    return plan


def _pydantic_errors(exc: ValidationError) -> list[FieldError]:
    return [
        FieldError(
            code="SCHEMA_VALIDATION_FAILED",
            path=".".join(str(part) for part in error["loc"]),
            message=str(error["msg"]),
        )
        for error in exc.errors(include_url=False, include_context=False)
    ]


def _first_difference(expected: Any, actual: Any, path: str = "plan") -> FieldError | None:
    if type(expected) is not type(actual):
        return FieldError(code="VALUE_CHANGED", path=path, message="value type changed")
    if isinstance(expected, dict):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing:
            return FieldError(
                code="FIELD_MISSING", path=f"{path}.{missing[0]}", message="field missing"
            )
        if extra:
            return FieldError(code="FIELD_ADDED", path=f"{path}.{extra[0]}", message="field added")
        for key in expected:
            different = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if different:
                return different
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return FieldError(code="VALUE_CHANGED", path=path, message="list length changed")
        for index, value in enumerate(expected):
            different = _first_difference(value, actual[index], f"{path}.{index}")
            if different:
                return different
        return None
    if expected != actual:
        return FieldError(code="VALUE_CHANGED", path=path, message="user value changed")
    return None


CheckpointCallback = Callable[[P1WorkflowState], Awaitable[None]]


class IntakeGraph:
    def __init__(
        self,
        capabilities: Capabilities,
        adapter: LLMAdapter,
        runs: ModelRunStore,
        *,
        checkpoint: CheckpointCallback | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.adapter = adapter
        self.runs = runs
        self.checkpoint = checkpoint
        builder = StateGraph(P1WorkflowState)
        builder.add_node("load_context", self.load_context)
        builder.add_node("normalize_input", self.normalize_input)
        builder.add_node("build_expected_constraints", self.build_expected_constraints)
        builder.add_node("generate_candidate", self.generate_candidate)
        builder.add_node("validate_schema", self.validate_schema)
        builder.add_node("validate_business_rules", self.validate_business_rules)
        builder.add_node("prepare_repair", self.prepare_repair)
        builder.add_node("finalize_success", self.finalize_success)
        builder.add_node("finalize_failure", self.finalize_failure)
        builder.add_edge(START, "load_context")
        builder.add_edge("load_context", "normalize_input")
        builder.add_edge("normalize_input", "build_expected_constraints")
        builder.add_conditional_edges(
            "build_expected_constraints",
            self.route_after_context,
            {"generate": "generate_candidate", "failure": "finalize_failure"},
        )
        builder.add_edge("generate_candidate", "validate_schema")
        builder.add_edge("validate_schema", "validate_business_rules")
        builder.add_conditional_edges(
            "validate_business_rules",
            self.route_after_validation,
            {
                "success": "finalize_success",
                "repair": "prepare_repair",
                "failure": "finalize_failure",
            },
        )
        builder.add_edge("prepare_repair", "generate_candidate")
        builder.add_edge("finalize_success", END)
        builder.add_edge("finalize_failure", END)
        self.graph = builder.compile()

    def load_context(self, state: P1WorkflowState) -> dict[str, Any]:
        if (
            state.capability_version != self.capabilities.version
            or self.capabilities.status != "VERIFIED"
            or self.capabilities.sample_kind != "live"
        ):
            return {
                "business_errors": [
                    FieldError(
                        code="CAPABILITY_VERSION_CHANGED",
                        path="capability_version",
                        message="submitted capability version is no longer active",
                    )
                ]
            }
        return {}

    def normalize_input(self, state: P1WorkflowState) -> dict[str, Any]:
        if state.business_errors:
            return {}
        return {"normalized_input": state.requirement_form.normalized()}

    def build_expected_constraints(self, state: P1WorkflowState) -> dict[str, Any]:
        if state.business_errors:
            return {}
        assert state.normalized_input
        try:
            expected = build_expected_plan(state.normalized_input, self.capabilities)
        except CollectorError as exc:
            return {
                "business_errors": [
                    FieldError(code=exc.code, path="requirement_form", message=exc.reason)
                ]
            }
        semantic = [item.field for item in expected.filters]
        return {
            "expected_constraints": expected.model_dump(mode="json"),
            "semantic_fields": semantic,
        }

    def route_after_context(self, state: P1WorkflowState) -> str:
        return "failure" if state.business_errors else "generate"

    async def generate_candidate(self, state: P1WorkflowState) -> dict[str, Any]:
        attempt = state.attempt_count + 1
        repair_errors = [*state.schema_errors, *state.business_errors]
        input_payload = {
            "form": state.normalized_input.model_dump(mode="json")
            if state.normalized_input
            else {},
            "capabilities": self.capabilities.model_dump(mode="json"),
            "expected": state.expected_constraints,
            "repair": [error.model_dump(mode="json") for error in repair_errors],
            "prompt_version": state.prompt_version,
        }
        input_digest = hashlib.sha256(
            json.dumps(input_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        updates: dict[str, Any] = {
            "attempt_count": attempt,
            "candidate_plan_json": None,
            "candidate_plan": None,
            "schema_errors": [],
            "business_errors": [],
        }
        existing = self.runs.existing_model_run(state.root_task_id, state.retry_cycle, attempt)
        if existing and existing.get("status") == "succeeded" and existing.get("output_payload"):
            updates["candidate_plan_json"] = existing["output_payload"]
            updates["model_run_ids"] = [
                *state.model_run_ids,
                str(existing["model_run_id"]),
            ]
            return updates
        if existing:
            run_id = str(existing["model_run_id"])
            if existing.get("status") == "started":
                self.runs.finish_model_run(
                    run_id,
                    status="indeterminate",
                    error_payload={"code": "AI_DELIVERY_INDETERMINATE"},
                    delivery_status="indeterminate",
                )
            updates["model_run_ids"] = [*state.model_run_ids, run_id]
            updates["business_errors"] = [
                FieldError(
                    code="AI_DELIVERY_INDETERMINATE",
                    path="model",
                    message="previous provider delivery could not be proven",
                )
            ]
            return updates
        run_state = state.model_copy(update={"attempt_count": attempt})
        run_id = self.runs.begin_model_run(
            run_state,
            provider=self.adapter.provider,
            requested_model=self.adapter.model,
            input_digest=input_digest,
        )
        started = time.monotonic()
        try:
            assert state.normalized_input
            result = await self.adapter.generate_filter_plan(
                form=state.normalized_input,
                capabilities=self.capabilities,
                expected_constraints=state.expected_constraints,
                prompt_version=state.prompt_version,
                repair_errors=repair_errors,
            )
        except LLMFailure as exc:
            self.runs.finish_model_run(
                run_id,
                status="indeterminate" if exc.indeterminate else "failed",
                error_payload={
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                },
                latency_ms=int((time.monotonic() - started) * 1000),
                delivery_status="indeterminate" if exc.indeterminate else "received",
            )
            updates["business_errors"] = [
                FieldError(code=exc.code, path="model", message=exc.message)
            ]
            if not exc.retryable:
                updates["attempt_count"] = state.max_attempts
        else:
            self.runs.finish_model_run(
                run_id,
                status="succeeded",
                response_model=result.response_model,
                output_payload=cast(dict[str, Any], result.payload),
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            updates["candidate_plan_json"] = result.payload
        updates["model_run_ids"] = [*state.model_run_ids, run_id]
        checkpoint_state = state.model_copy(update=updates)
        if self.checkpoint:
            await self.checkpoint(checkpoint_state)
        return updates

    def validate_schema(self, state: P1WorkflowState) -> dict[str, Any]:
        if state.business_errors or state.candidate_plan_json is None:
            return {}
        try:
            plan = FilterPlan.model_validate(state.candidate_plan_json)
        except ValidationError as exc:
            return {"schema_errors": _pydantic_errors(exc), "candidate_plan": None}
        return {"schema_errors": [], "candidate_plan": plan}

    def validate_business_rules(self, state: P1WorkflowState) -> dict[str, Any]:
        if state.business_errors or state.schema_errors or state.candidate_plan is None:
            return {}
        actual = state.candidate_plan.model_dump(mode="json")
        different = _first_difference(state.expected_constraints, actual)
        if different:
            return {"business_errors": [different]}
        try:
            self.capabilities.validate_plan(state.candidate_plan, live=True)
        except CollectorError as exc:
            return {"business_errors": [FieldError(code=exc.code, path="plan", message=exc.reason)]}
        return {"business_errors": []}

    def route_after_validation(self, state: P1WorkflowState) -> str:
        if not state.schema_errors and not state.business_errors and state.candidate_plan:
            return "success"
        nonrepairable = {
            "CAPABILITY_VERSION_CHANGED",
            "AI_AUTH_OR_QUOTA",
            "AI_PROVIDER_REJECTED",
        }
        errors = [*state.schema_errors, *state.business_errors]
        if state.attempt_count < state.max_attempts and not any(
            error.code in nonrepairable for error in errors
        ):
            return "repair"
        return "failure"

    def prepare_repair(self, state: P1WorkflowState) -> dict[str, Any]:
        # Error details stay structured and are supplied on the next bounded model call.
        return {"candidate_plan": None, "candidate_plan_json": None}

    def finalize_success(self, state: P1WorkflowState) -> dict[str, Any]:
        assert state.candidate_plan
        return {
            "final_plan": state.candidate_plan,
            "final_error": [],
            "outcome": "succeeded",
        }

    def finalize_failure(self, state: P1WorkflowState) -> dict[str, Any]:
        errors = [*state.schema_errors, *state.business_errors]
        model_codes = {
            "AI_TRANSPORT_ERROR",
            "AI_PROVIDER_RETRYABLE",
            "AI_AUTH_OR_QUOTA",
            "AI_PROVIDER_REJECTED",
            "AI_INCOMPLETE_RESPONSE",
            "AI_EMPTY_OUTPUT",
            "AI_INVALID_RESPONSE",
            "AI_INVALID_JSON",
            "AI_DELIVERY_INDETERMINATE",
        }
        return {
            "final_error": errors,
            "outcome": "failed_model"
            if errors and all(error.code in model_codes for error in errors)
            else "failed_validation",
        }

    async def run(self, state: P1WorkflowState) -> P1WorkflowState:
        result = await self.graph.ainvoke(state)
        return P1WorkflowState.model_validate(result)
