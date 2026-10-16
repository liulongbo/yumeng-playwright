from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from .domain import Capabilities, FilterPlan, Model, TaskStatus


class RequirementRange(Model):
    min: Decimal | None = None
    max: Decimal | None = None
    unit: Literal["count", "ten_thousand_count"] = "ten_thousand_count"

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


class RegionSelection(Model):
    province_code: str = Field(min_length=1)
    city: str | None = None

    @model_validator(mode="after")
    def nonblank(self) -> Self:
        if not self.province_code.strip():
            raise ValueError("province_code cannot be blank")
        if self.city is not None and not self.city.strip():
            raise ValueError("city cannot be blank")
        return self


class ConnectionUsersRequirement(Model):
    connected: RequirementRange | None = None
    aware: RequirementRange | None = None
    interested: RequirementRange | None = None
    liked: RequirementRange | None = None
    followed: RequirementRange | None = None

    @model_validator(mode="after")
    def at_least_one_range(self) -> Self:
        if not any((self.connected, self.aware, self.interested, self.liked, self.followed)):
            raise ValueError("at least one connection user range is required")
        for value in (self.connected, self.aware, self.interested, self.liked, self.followed):
            if value is not None and value.unit != "ten_thousand_count":
                raise ValueError("connection user ranges use ten_thousand_count")
            if value is not None and any(
                bound is not None and bound > 100 for bound in (value.min, value.max)
            ):
                raise ValueError("connection user range exceeds 100w")
        return self


class AudienceProfileRequirement(Model):
    age: list[Literal["age_18_23", "age_24_30", "age_31_40", "age_41_50", "age_over_50"]] = Field(
        default_factory=list
    )
    gender: (
        Literal[
            "male_50",
            "male_60",
            "male_70",
            "male_80",
            "female_50",
            "female_60",
            "female_70",
            "female_80",
        ]
        | None
    ) = None
    device_brand: list[Literal["apple", "huawei", "xiaomi", "vivo", "oppo"]] = Field(
        default_factory=list
    )
    city_level: list[Literal["tier_1", "tier_2", "tier_3", "tier_4", "tier_5"]] = Field(
        default_factory=list
    )
    crowd: list[
        Literal[
            "gen_z",
            "town_youth",
            "new_white_collar",
            "refined_mother",
            "urban_blue_collar",
            "town_middle_aged",
            "senior_middle_class",
            "urban_silver",
        ]
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def meaningful_and_unique(self) -> Self:
        groups = (self.age, self.device_brand, self.city_level, self.crowd)
        if not any((*groups, self.gender is not None)):
            raise ValueError("at least one audience profile dimension is required")
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("audience profile options must be unique")
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

    schema_version: Literal["requirement_form.v1", "requirement_form.v2"] = "requirement_form.v2"
    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    keyword: str | None = None
    creator_types: list[str] = Field(default_factory=list)
    followers: RequirementRange | None = None
    creator_gender: str | None = None
    creator_regions: list[str | RegionSelection] = Field(default_factory=list)
    creator_education: Literal["undergraduate", "master", "doctor", "overseas"] | None = None
    yellow_v_certification: (
        Literal["beauty", "sports", "media_host", "technology", "athlete"] | None
    ) = None
    connection_users: ConnectionUsersRequirement | None = None
    viewer_profile: AudienceProfileRequirement | None = None
    fan_profile: AudienceProfileRequirement | None = None
    quote: QuoteRequirement | None = None
    sort_key: str | None = None
    target_count: int = Field(default=20, ge=1, le=200, strict=True)

    @model_validator(mode="after")
    def meaningful_and_unique(self) -> Self:
        if self.keyword is not None and not self.keyword.strip():
            raise ValueError("keyword cannot be blank")
        if any(not value.strip() for value in self.creator_types):
            raise ValueError("filter options cannot be blank")
        if len(self.creator_types) != len(set(self.creator_types)):
            raise ValueError("filter options must be unique")
        if self.creator_gender is not None and not self.creator_gender.strip():
            raise ValueError("creator_gender cannot be blank")
        if self.sort_key is not None and not self.sort_key.strip():
            raise ValueError("sort_key cannot be blank")
        if self.schema_version == "requirement_form.v1":
            if any(not isinstance(value, str) for value in self.creator_regions):
                raise ValueError("v1 creator_regions must be strings")
            if any(
                (
                    self.creator_education,
                    self.yellow_v_certification,
                    self.connection_users,
                    self.viewer_profile,
                    self.fan_profile,
                )
            ):
                raise ValueError("v2 filters are not valid in requirement_form.v1")
        else:
            if self.creator_types or self.quote is not None:
                raise ValueError("legacy filters are not valid in requirement_form.v2")
            if any(isinstance(value, str) for value in self.creator_regions):
                raise ValueError("v2 creator_regions must be structured paths")
            if self.creator_gender not in {None, "male", "female"}:
                raise ValueError("creator_gender must be male or female")
            if self.followers is not None:
                if self.followers.unit != "ten_thousand_count":
                    raise ValueError("followers use ten_thousand_count")
                if any(
                    bound is not None and bound > 5000
                    for bound in (self.followers.min, self.followers.max)
                ):
                    raise ValueError("followers range exceeds 5000w")
            paths = [value for value in self.creator_regions if isinstance(value, RegionSelection)]
            path_keys = [(value.province_code, value.city) for value in paths]
            if len(path_keys) != len(set(path_keys)):
                raise ValueError("creator region paths must be unique")
            whole_provinces = {value.province_code for value in paths if value.city is None}
            if any(
                value.city is not None and value.province_code in whole_provinces for value in paths
            ):
                raise ValueError("a province and its child city cannot both be selected")
            if self.viewer_profile is not None and self.fan_profile is not None:
                raise ValueError("viewer_profile and fan_profile are mutually exclusive")
        if not any(
            (
                self.keyword is not None,
                bool(self.creator_types),
                self.followers is not None,
                self.creator_gender is not None,
                bool(self.creator_regions),
                self.quote is not None,
                self.creator_education is not None,
                self.yellow_v_certification is not None,
                self.connection_users is not None,
                self.viewer_profile is not None,
                self.fan_profile is not None,
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
        if self.schema_version == "requirement_form.v1":
            data["creator_regions"] = sorted(
                value.strip() for value in self.creator_regions if isinstance(value, str)
            )
        else:
            data["creator_regions"] = sorted(
                (
                    value.model_dump(mode="json")
                    for value in self.creator_regions
                    if isinstance(value, RegionSelection)
                ),
                key=lambda value: (value["province_code"], value.get("city") or ""),
            )
            for value in data["creator_regions"]:
                value["province_code"] = value["province_code"].strip()
                if value.get("city") is not None:
                    value["city"] = value["city"].strip()
        if self.creator_gender is not None:
            data["creator_gender"] = self.creator_gender.strip()
        if self.sort_key is not None:
            data["sort_key"] = self.sort_key.strip()
        return RequirementForm.model_validate(data)


class CapabilityFieldDTO(Model):
    field: str
    label: str
    operators: list[str]
    group: str | None = None
    control: str | None = None
    options: list[dict[str, JsonValue]] = Field(default_factory=list)
    dimensions: list[dict[str, JsonValue]] = Field(default_factory=list)
    region_tree: list[dict[str, JsonValue]] = Field(default_factory=list)
    range_constraints: dict[str, JsonValue] | None = None
    incompatible_with: list[str] = Field(default_factory=list)
    unit: str | None = None
    currencies: list[str] = Field(default_factory=list)
    cooperation_forms: list[str] = Field(default_factory=list)
    keyword_mode: str | None = None


class CapabilityDTO(Model):
    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    capability_version: str
    fields: list[CapabilityFieldDTO]
    combinations: list[list[str]]
    combination_policy: dict[str, JsonValue] | None = None
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
                    label=item.label or labels.get(item.field, item.field),
                    operators=item.operators,
                    group=item.group,
                    control=item.control,
                    options=[option.model_dump(mode="json") for option in item.options],
                    dimensions=[item.model_dump(mode="json") for item in item.dimensions],
                    region_tree=[item.model_dump(mode="json") for item in item.region_tree],
                    range_constraints=item.range_constraints.model_dump(mode="json")
                    if item.range_constraints
                    else None,
                    incompatible_with=item.incompatible_with,
                    unit=item.unit,
                    currencies=item.currencies,
                    cooperation_forms=item.cooperation_forms,
                    keyword_mode=item.keyword_mode,
                )
                for item in capabilities.fields
            ],
            combinations=capabilities.combinations,
            combination_policy=capabilities.combination_policy.model_dump(mode="json")
            if capabilities.combination_policy
            else None,
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
    prompt_version: str = "m3-filter-plan-v2"
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
    # Last write to the task record (any state or version change). Not a completion moment.
    updated_at: datetime
    # Moment the task first entered a terminal state; null while it is still progressing.
    completed_at: datetime | None = None
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


class LibraryMetric(Model):
    """A platform-native metric; no currency, percentage or cross-platform meaning is inferred."""

    value: Decimal | None = None
    raw_value: str | None = None
    unit: str | None = None
    is_approximate: bool = False
    status: str = "NOT_AVAILABLE"
    observed_at: datetime | None = None


class CreatorLibrarySummary(Model):
    creator_id: str
    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    platform_creator_id: str
    display_name: str | None = None
    avatar_uri: str | None = None
    creator_type_label: str | None = None
    province: str | None = None
    city: str | None = None
    industry_labels: list[str] = Field(default_factory=list)
    followers: LibraryMetric
    monthly_deep_users: LibraryMetric
    monthly_connected_users: LibraryMetric
    monthly_follower_growth_rate: LibraryMetric
    interaction_rate: LibraryMetric
    completion_rate: LibraryMetric
    expected_cpm_21_60: LibraryMetric
    expected_cpm_60_plus: LibraryMetric
    expected_cpe_21_60: LibraryMetric
    expected_cpe_60_plus: LibraryMetric
    profile_complete: bool
    pipeline_complete: bool
    data_updated_at: datetime | None = None


class CreatorLibraryPage(Model):
    items: list[CreatorLibrarySummary]
    next_cursor: str | None = None


class CreatorLibraryDetail(CreatorLibrarySummary):
    latest_snapshot_id: str | None = None
    mcn_name: str | None = None
    introduction: str | None = None
    # `basic.gender` exactly as the platform stored it (its numeric code).  Only the presentation
    # layer maps a code to a label, and only for codes verified against the live platform (see
    # frontend/src/profile/views.ts).  Read from the same current projection as `introduction`.
    gender: str | None = None
    content_theme_labels: list[str] = Field(default_factory=list)
    collected_field_count: int = 0
    failed_field_count: int = 0
    field_sources: dict[str, JsonValue] = Field(default_factory=dict)
    module_statuses: dict[str, str | None] = Field(default_factory=dict)
    # A presentation-safe, complete profile assembled from the current projection and the latest
    # immutable snapshot.  It deliberately keeps platform field envelopes (status/unit/period).
    profile_payload: dict[str, JsonValue] = Field(default_factory=dict)


class CreatorLibraryHistoryPoint(Model):
    snapshot_id: str
    captured_at: datetime
    profile_complete: bool
    pipeline_complete: bool
    module_statuses: dict[str, str | None] = Field(default_factory=dict)
    metrics: dict[str, Decimal | None] = Field(default_factory=dict)


class CreatorLibraryHistory(Model):
    items: list[CreatorLibraryHistoryPoint]
    # Snapshots of this creator that have a library index row, against every stored snapshot.
    # The detail page discloses the difference instead of presenting a partial history as complete.
    indexed_snapshots: int = 0
    total_snapshots: int = 0


class CreatorLibraryQuote(Model):
    snapshot_id: str
    position: int
    cooperation_form: str | None = None
    settlement_description: str | None = None
    price_raw: Decimal | None = None
    origin_price_raw: Decimal | None = None
    observed_at: datetime
    offer_raw: dict[str, JsonValue] = Field(default_factory=dict)


class ProfileFieldCatalogEntry(Model):
    """Presentation metadata for one registered profile field; never a collected business value."""

    key: str
    name: str
    contract_name: str
    name_source: Literal["contract", "evidence_correction"] = "contract"
    kind: str
    unit: str | None = None
    period_label: str | None = None
    empty_values: list[str] = Field(default_factory=list)
    missing_source_status: str | None = None


class ProfileModuleCatalog(Model):
    key: str
    fields: list[ProfileFieldCatalogEntry]


class ProfileFieldCatalog(Model):
    """Read-only field registry slice used to label and format the creator detail page."""

    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    contract_version: str
    modules: list[ProfileModuleCatalog]
