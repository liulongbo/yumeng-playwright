from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from .domain import Capabilities, FilterPlan, Model, TaskStatus


class RequirementRange(Model):
    min: Decimal | None = None
    max: Decimal | None = None
    unit: Literal["count"] = "count"

    @model_validator(mode="after")
    def ordered(self) -> Self:
        values = [value for value in (self.min, self.max) if value is not None]
        if not values:
            raise ValueError("at least one range bound is required")
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("range bounds must be finite and nonnegative")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("range is reversed")
        return self


class QuoteRequirement(Model):
    cooperation_form: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    min: Decimal | None = None
    max: Decimal | None = None
    unit: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        values = [value for value in (self.min, self.max) if value is not None]
        if not values:
            raise ValueError("at least one quote bound is required")
        if any(not value.is_finite() or value < 0 for value in values):
            raise ValueError("quote bounds must be finite and nonnegative")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("quote range is reversed")
        return self


class RequirementForm(Model):
    """The user-authored requirement, deliberately separate from ``FilterPlan``."""

    schema_version: Literal["requirement_form.v1"] = "requirement_form.v1"
    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    keyword: str | None = None
    creator_types: list[str] = Field(default_factory=list)
    followers: RequirementRange | None = None
    creator_gender: str | None = None
    creator_regions: list[str] = Field(default_factory=list)
    quote: QuoteRequirement | None = None
    sort_key: str | None = None
    target_count: int = Field(default=20, ge=1, le=200, strict=True)

    @model_validator(mode="after")
    def meaningful_and_unique(self) -> Self:
        if self.keyword is not None and not self.keyword.strip():
            raise ValueError("keyword cannot be blank")
        list_fields = (self.creator_types, self.creator_regions)
        if any(any(not value.strip() for value in values) for values in list_fields):
            raise ValueError("filter options cannot be blank")
        if any(len(values) != len(set(values)) for values in list_fields):
            raise ValueError("filter options must be unique")
        if self.creator_gender is not None and not self.creator_gender.strip():
            raise ValueError("creator_gender cannot be blank")
        if self.sort_key is not None and not self.sort_key.strip():
            raise ValueError("sort_key cannot be blank")
        if not any(
            (
                self.keyword is not None,
                bool(self.creator_types),
                self.followers is not None,
                self.creator_gender is not None,
                bool(self.creator_regions),
                self.quote is not None,
            )
        ):
            raise ValueError("at least one business filter is required")
        return self

    def normalized(self) -> RequirementForm:
        """Apply only lossless presentation normalization; never rewrite user meaning."""
        data = self.model_dump()
        if self.keyword is not None:
            data["keyword"] = self.keyword.strip()
        data["creator_types"] = sorted(value.strip() for value in self.creator_types)
        data["creator_regions"] = sorted(value.strip() for value in self.creator_regions)
        if self.creator_gender is not None:
            data["creator_gender"] = self.creator_gender.strip()
        if self.sort_key is not None:
            data["sort_key"] = self.sort_key.strip()
        return RequirementForm.model_validate(data)


class CapabilityFieldDTO(Model):
    field: str
    label: str
    operators: list[str]
    options: list[str] = Field(default_factory=list)
    unit: str | None = None
    currencies: list[str] = Field(default_factory=list)
    cooperation_forms: list[str] = Field(default_factory=list)
    keyword_mode: str | None = None


class CapabilityDTO(Model):
    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    capability_version: str
    fields: list[CapabilityFieldDTO]
    combinations: list[list[str]]
    target_count_default: int = 20
    target_count_min: int = 1
    target_count_max: int = 200
    fixed_sort_key: str
    fixed_sort_label: str = "平台默认排序"

    @classmethod
    def from_capabilities(cls, capabilities: Capabilities) -> CapabilityDTO:
        if capabilities.status != "VERIFIED" or capabilities.sample_kind != "live":
            raise ValueError("only live verified capabilities may be exposed")
        labels = {
            "keyword": "内容关键词",
            "creator_type": "达人类型",
            "followers": "粉丝量",
            "gender": "性别",
            "region": "地域",
            "quote": "报价",
        }
        if len(capabilities.sorts) != 1:
            raise ValueError("M3 requires one verified platform default sort")
        return cls(
            capability_version=capabilities.version,
            fields=[
                CapabilityFieldDTO(
                    field=item.field,
                    label=labels.get(item.field, item.field),
                    operators=item.operators,
                    options=item.enum,
                    unit=item.unit,
                    currencies=item.currencies,
                    cooperation_forms=item.cooperation_forms,
                    keyword_mode=item.keyword_mode,
                )
                for item in capabilities.fields
            ],
            combinations=capabilities.combinations,
            fixed_sort_key=capabilities.sorts[0],
        )


class FieldError(Model):
    code: str
    path: str
    message: str


class P1WorkflowState(Model):
    schema_version: Literal["p1_state.v1"] = "p1_state.v1"
    root_task_id: str
    requirement_id: str
    p1_task_id: str
    requirement_form: RequirementForm
    capability_version: str
    capability_snapshot_ref: str
    normalized_input: RequirementForm | None = None
    expected_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    semantic_fields: list[str] = Field(default_factory=list)
    candidate_plan_json: dict[str, JsonValue] | None = None
    candidate_plan: FilterPlan | None = None
    schema_errors: list[FieldError] = Field(default_factory=list)
    business_errors: list[FieldError] = Field(default_factory=list)
    retry_cycle: int = Field(default=0, ge=0)
    attempt_count: int = Field(default=0, ge=0, le=3)
    max_attempts: Literal[3] = 3
    prompt_version: str = "m3-filter-plan-v1"
    model_config_id: str
    model_run_ids: list[str] = Field(default_factory=list)
    final_plan: FilterPlan | None = None
    final_error: list[FieldError] = Field(default_factory=list)
    outcome: Literal["pending", "succeeded", "failed_validation", "failed_model"] = "pending"


class ModelUsage(Model):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class LLMResult(Model):
    payload: dict[str, JsonValue]
    response_model: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)


class AuthenticatedUser(Model):
    user_id: str
    username: str
    display_name: str
    session_id: str
    csrf_token: str


class LoginRequest(Model):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class UserView(Model):
    user_id: str
    username: str
    display_name: str
    csrf_token: str


class CreateTaskResponse(Model):
    root_task_id: str
    status: Literal["RECEIVED"] = "RECEIVED"


class ProductError(Model):
    code: str
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)
    request_id: str
    current_version: int | None = None
    allowed_actions: list[str] = Field(default_factory=list)


class TaskCounts(Model):
    target_count: int
    discovered_count: int = 0
    valid_count: int = 0
    profile_complete_count: int = 0
    featured_complete_count: int = 0
    failed_count: int = 0


class ChallengeSummary(Model):
    state: str
    challenge_type: str | None = None
    first_detected_at: datetime | None = None
    last_detected_at: datetime | None = None
    wait_started_at: datetime | None = None
    last_recovered_at: datetime | None = None
    detected_count: int = 0
    recovery_count: int = 0
    current_creator_id: str | None = None
    completed_creator_count: int = 0
    remaining_creator_count: int = 0
    waiting_seconds: int = 0
    account_matches: bool | None = None
    requires_user_action: bool = False
    monitoring: bool = False
    terminal_reason: str | None = None
    terminal_message: str | None = None
    delivered_result: str


class TaskSummary(Model):
    root_task_id: str
    status: TaskStatus
    stage: str
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    created_by_name: str | None = None
    source: Literal["product", "internal_acceptance"]
    keyword: str | None = None
    counts: TaskCounts
    allowed_actions: list[str]
    failure_reason: str | None = None


class IntakeProgress(Model):
    """Why a product task is still waiting for the P1 conversion workflow.

    ``sent=false`` alone cannot tell "no consumer process is running" apart from "the consumer is
    alive but has not polled yet" or "dispatch keeps failing". ``consumer_alive`` is a real
    observation of the Temporal task queue (tri-state: ``None`` = not observable right now), and
    ``blocked_reason`` is only set when a missing consumer is actually confirmed.
    """

    sent: bool = False
    pending_seconds: float | None = None
    consumer_alive: bool | None = None
    consumer_checked_at: datetime | None = None
    observed_fresh_pollers: int | None = None
    dispatch_error: str | None = None
    blocked_reason: str | None = None
    blocked_seconds: float | None = None

    @property
    def is_blocked(self) -> bool:
        return self.blocked_reason is not None


class TaskDetail(TaskSummary):
    requirement: RequirementForm | None = None
    capability_version: str | None = None
    plan: FilterPlan | None = None
    field_errors: list[FieldError] = Field(default_factory=list)
    origin_root_task_id: str | None = None
    challenge: ChallengeSummary | None = None
    intake: IntakeProgress | None = None


class TaskPage(Model):
    items: list[TaskSummary]
    next_cursor: str | None = None


class CommandRequest(Model):
    expected_version: int = Field(ge=0, strict=True)


class CreatorSummary(Model):
    creator_id: str
    platform_creator_id: str
    first_position: int
    view_kind: Literal["draft", "published"]
    snapshot_id: str | None = None
    observed_at: datetime | None = None
    payload: dict[str, JsonValue]


class CreatorPage(Model):
    items: list[CreatorSummary]
    next_cursor: str | None = None
