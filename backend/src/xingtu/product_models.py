from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from .domain import (
    CONNECTION_USERS_MAX_W,
    LIVE_OPTION_FIELDS,
    LIVE_PROFILE_FIELDS,
    LIVE_RANGE_FIELDS,
    Capabilities,
    CreatorScene,
    FilterPlan,
    Model,
    TaskKind,
    TaskStatus,
)


class RequirementRange(Model):
    min: Decimal | None = None
    max: Decimal | None = None
    unit: Literal["count", "ten_thousand_count", "yuan"] = "ten_thousand_count"

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
                bound is not None and bound > CONNECTION_USERS_MAX_W
                for bound in (value.min, value.max)
            ):
                raise ValueError("connection user range exceeds 99999w")
            if value is not None and any(
                bound is not None and bound != bound.to_integral_value()
                for bound in (value.min, value.max)
            ):
                raise ValueError("connection user ranges use whole ten-thousand counts")
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


class JuxingVideoQuotes(Model):
    seconds_1_20: RequirementRange | None = None
    seconds_21_60: RequirementRange | None = None
    seconds_60_plus: RequirementRange | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> JuxingVideoQuotes:
        if not any((self.seconds_1_20, self.seconds_21_60, self.seconds_60_plus)):
            raise ValueError("at least one video quote range is required")
        for value in (self.seconds_1_20, self.seconds_21_60, self.seconds_60_plus):
            if value is not None and value.unit != "yuan":
                raise ValueError("kuaishou video quotes use yuan")
        return self


LiveFilterField = Literal[
    "live_content_type",
    "live_content_category",
    "live_gender",
    "live_certification",
    "live_region",
    "live_followers",
    "live_recent_sessions",
    "live_avg_viewers",
    "live_avg_view_visits",
    "live_acu",
    "live_pcu",
    "live_expected_viewers",
    "live_max_online",
    "live_expected_cpm",
    "live_viewer_profile",
    "live_fan_profile",
]


class LiveProfileDimensionRequirement(Model):
    key: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def nonblank_and_unique(self) -> Self:
        if not self.key.strip() or any(not value.strip() for value in self.values):
            raise ValueError("live profile values cannot be blank")
        if len(self.values) != len(set(self.values)):
            raise ValueError("live profile values must be unique")
        return self


class LiveFilterRequirement(Model):
    field: LiveFilterField
    values: list[str] = Field(default_factory=list)
    range: RequirementRange | None = None
    regions: list[RegionSelection] = Field(default_factory=list)
    profile: list[LiveProfileDimensionRequirement] = Field(default_factory=list)

    @model_validator(mode="after")
    def shape(self) -> Self:
        payloads = {
            "values": bool(self.values),
            "range": self.range is not None,
            "regions": bool(self.regions),
            "profile": bool(self.profile),
        }
        if sum(payloads.values()) != 1:
            raise ValueError("live filter requires exactly one value shape")
        if self.field in LIVE_OPTION_FIELDS and not payloads["values"]:
            raise ValueError("live option filter requires values")
        if self.field in LIVE_RANGE_FIELDS and not payloads["range"]:
            raise ValueError("live range filter requires a range")
        if self.field in LIVE_PROFILE_FIELDS and not payloads["profile"]:
            raise ValueError("live profile filter requires profile dimensions")
        if self.field == "live_region" and not payloads["regions"]:
            raise ValueError("live region filter requires regions")
        if len(self.values) != len(set(self.values)):
            raise ValueError("live filter values must be unique")
        keys = [(value.province_code, value.city) for value in self.regions]
        if len(keys) != len(set(keys)):
            raise ValueError("live region paths must be unique")
        profile_keys = [value.key for value in self.profile]
        if len(profile_keys) != len(set(profile_keys)):
            raise ValueError("live profile dimensions must be unique")
        return self


class RequirementForm(Model):
    """The user-authored requirement, deliberately separate from ``FilterPlan``."""

    schema_version: Literal["requirement_form.v1", "requirement_form.v2", "requirement_form.v3"] = (
        "requirement_form.v2"
    )
    platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu"
    creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE
    keyword: str | None = None
    live_filters: list[LiveFilterRequirement] = Field(default_factory=list)
    content_types: list[str] = Field(default_factory=list)
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
    juxing_video_quotes: JuxingVideoQuotes | None = None
    sort_key: str | None = None
    target_count: int = Field(default=20, ge=1, le=200, strict=True)

    @model_validator(mode="after")
    def meaningful_and_unique(self) -> Self:
        if self.keyword is not None and not self.keyword.strip():
            raise ValueError("keyword cannot be blank")
        if self.creator_scene != CreatorScene.LIVE_SQUARE and self.live_filters:
            raise ValueError("live filters are only valid for live_square")
        if self.creator_scene == CreatorScene.LIVE_SQUARE:
            if self.target_count > 70:
                raise ValueError("live target_count exceeds 70")
            if (self.keyword is None or not self.keyword.strip()) and not self.live_filters:
                raise ValueError("live collection requires a keyword, creator id or filter")
            if any(
                (
                    self.content_types,
                    self.creator_types,
                    self.followers,
                    self.creator_gender,
                    self.creator_regions,
                    self.creator_education,
                    self.yellow_v_certification,
                    self.connection_users,
                    self.viewer_profile,
                    self.fan_profile,
                    self.quote,
                    self.juxing_video_quotes,
                )
            ):
                raise ValueError("live collection does not support video filters yet")
            live_fields = [value.field for value in self.live_filters]
            if len(live_fields) != len(set(live_fields)):
                raise ValueError("live filter fields must be unique")
        if any(not value.strip() for value in self.creator_types):
            raise ValueError("filter options cannot be blank")
        if len(self.creator_types) != len(set(self.creator_types)):
            raise ValueError("filter options must be unique")
        if any(not value.strip() for value in self.content_types) or len(self.content_types) != len(
            set(self.content_types)
        ):
            raise ValueError("content_types must be nonblank and unique")
        if self.creator_gender is not None and not self.creator_gender.strip():
            raise ValueError("creator_gender cannot be blank")
        if self.sort_key is not None and not self.sort_key.strip():
            raise ValueError("sort_key cannot be blank")
        if self.platform == "kuaishou_juxing":
            if self.schema_version != "requirement_form.v3":
                raise ValueError("kuaishou_juxing requires requirement_form.v3")
            if any(
                (
                    self.creator_types,
                    self.creator_gender,
                    self.creator_education,
                    self.yellow_v_certification,
                    self.connection_users,
                    self.viewer_profile,
                    self.fan_profile,
                    self.quote,
                )
            ):
                raise ValueError("unsupported kuaishou_juxing P0 filter")
            if self.followers is not None and self.followers.unit != "count":
                raise ValueError("kuaishou followers use count")
            if any(isinstance(value, str) for value in self.creator_regions):
                raise ValueError("kuaishou creator_regions must be structured paths")
        elif self.schema_version == "requirement_form.v1":
            if self.content_types or self.juxing_video_quotes is not None:
                raise ValueError("kuaishou filters are not valid in requirement_form.v1")
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
        elif self.schema_version == "requirement_form.v2":
            if (
                self.creator_types
                or self.quote is not None
                or self.content_types
                or self.juxing_video_quotes is not None
            ):
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
                bool(self.content_types),
                bool(self.creator_types),
                self.followers is not None,
                self.creator_gender is not None,
                bool(self.creator_regions),
                self.quote is not None,
                self.juxing_video_quotes is not None,
                self.creator_education is not None,
                self.yellow_v_certification is not None,
                self.connection_users is not None,
                self.viewer_profile is not None,
                self.fan_profile is not None,
                bool(self.live_filters),
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
        data["content_types"] = sorted(value.strip() for value in self.content_types)
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
        normalized_live: list[dict[str, object]] = []
        for item in self.live_filters:
            value = item.model_dump(mode="json")
            value["values"] = sorted(part.strip() for part in item.values)
            value["regions"] = sorted(
                (
                    {
                        "province_code": region.province_code.strip(),
                        "city": region.city.strip() if region.city else None,
                    }
                    for region in item.regions
                ),
                key=lambda region: (region["province_code"], region["city"] or ""),
            )
            value["profile"] = sorted(
                (
                    {
                        "key": profile.key.strip(),
                        "values": sorted(part.strip() for part in profile.values),
                    }
                    for profile in item.profile
                ),
                key=lambda profile: profile["key"],
            )
            normalized_live.append(value)
        data["live_filters"] = sorted(normalized_live, key=lambda value: value["field"])
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
    disabled_reason: str | None = None
    unit: str | None = None
    currencies: list[str] = Field(default_factory=list)
    cooperation_forms: list[str] = Field(default_factory=list)
    keyword_mode: str | None = None


class CapabilityDTO(Model):
    platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu"
    creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE
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
    def from_capabilities(
        cls,
        capabilities: Capabilities,
        *,
        platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu",
        creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE,
        target_count_max: int | None = None,
    ) -> CapabilityDTO:
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
            platform=platform,
            creator_scene=creator_scene,
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
                    disabled_reason=item.disabled_reason,
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
            target_count_default=(
                20
                if creator_scene == CreatorScene.LIVE_SQUARE
                else (
                    min(20, max(1, target_count_max or 200))
                    if platform == "kuaishou_juxing"
                    else 20
                )
            ),
            target_count_max=(
                70
                if creator_scene == CreatorScene.LIVE_SQUARE
                else (max(1, target_count_max or 200) if platform == "kuaishou_juxing" else 200)
            ),
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


class ManualProbeCreator(Model):
    """Presentation-only suggestion for a human using the existing browser window."""

    platform_creator_id: str
    display_name: str | None = None
    state: str


class VerificationEventView(Model):
    event_id: str
    unit_id: str
    root_task_id: str
    state: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED", "EXPIRED"]
    reason: str
    detected_at: datetime
    last_detected_at: datetime
    deadline_at: datetime
    reappearance_count: int = 0
    remaining_seconds: int = 0


class BrowserTakeoverView(Model):
    takeover_id: str
    unit_id: str
    root_task_id: str
    state: Literal["REQUESTED", "ACTIVE", "VERIFYING", "RESUMED", "FAILED", "EXPIRED", "RELEASED"]
    expires_at: datetime
    failure_reason: str | None = None
    viewer_url: str | None = None
    access_mode: Literal["LOCAL_WINDOW", "REMOTE_VIEWER"] = "LOCAL_WINDOW"
    operator_message: str | None = None
    manual_probe_creators: list[ManualProbeCreator] = Field(default_factory=list)


class ExecutionUnitView(Model):
    unit_id: str
    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    platforms: list[Literal["douyin_xingtu", "kuaishou_juxing"]] = ["douyin_xingtu"]
    account_label: str
    line_label: str
    state: str
    mode: str | None = None
    allowed_task_kinds: list[str] = Field(default_factory=list)
    current_root_task_id: str | None = None
    worker_status: Literal["ONLINE", "OFFLINE", "DUPLICATE", "UNKNOWN"] = "UNKNOWN"
    worker_instances: int = 0
    worker_last_heartbeat_at: datetime | None = None
    browser_status: Literal["ONLINE", "MAINTENANCE", "STOPPED", "SUSPECTED_OFFLINE", "QUARANTINED"]
    verification_state: str | None = None
    takeover_state: str | None = None
    verification_deadline_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    actionable_reason: str | None = None


class TaskSummary(Model):
    root_task_id: str
    platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu"
    creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE
    task_kind: TaskKind = TaskKind.COLLECTION
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


class UpdateTargetView(Model):
    """One creator targeted by a manual/scheduled update, with its checkpoint state."""

    creator_id: str | None = None
    platform_creator_id: str
    display_name: str | None = None
    first_position: int = 0
    state: Literal["pending", "collecting", "done", "invalid", "failed"] = "pending"
    failure_reason: str | None = None


class RetryPlan(Model):
    """What one retry click would do, derived from the task's own counts.

    The scope is not stored: it follows ``valid_count`` vs ``target_count`` so the API, the CLI
    command and the engine cannot disagree after the task is re-read.  ``last_retry_at`` and
    ``changed_since_last_retry`` are read from the existing audit and snapshot rows; no new column
    and no checkpoint field is involved.
    """

    scope: Literal["continue", "backfill"]
    remaining_to_target: int = 0
    incomplete_valid_count: int = 0
    retryable_creator_count: int = 0
    search_exhausted: bool = False
    # Last user retry recorded in audit_logs, and how many creator snapshots it changed.
    last_retry_at: datetime | None = None
    changed_since_last_retry: int | None = None


class TaskDetail(TaskSummary):
    requirement: RequirementForm | None = None
    capability_version: str | None = None
    plan: FilterPlan | None = None
    field_errors: list[FieldError] = Field(default_factory=list)
    origin_root_task_id: str | None = None
    challenge: ChallengeSummary | None = None
    intake: IntakeProgress | None = None
    update_targets: list[UpdateTargetView] = Field(default_factory=list)
    retry_plan: RetryPlan | None = None


class TaskPage(Model):
    items: list[TaskSummary]
    next_cursor: str | None = None


class CommandRequest(Model):
    expected_version: int = Field(ge=0, strict=True)


class CreatorSummary(Model):
    creator_id: str
    # The shared task-result query is platform-agnostic; the platform travels with each creator so
    # the product view can label and format it without a second request or a guessed default.
    platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu"
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
    platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu"
    creator_scene: CreatorScene = CreatorScene.VIDEO_SQUARE
    platform_creator_id: str
    live_metrics: dict[str, JsonValue] = Field(default_factory=dict)
    display_name: str | None = None
    avatar_uri: str | None = None
    creator_type_label: str | None = None
    province: str | None = None
    city: str | None = None
    industry_labels: list[str] = Field(default_factory=list)
    # The platform's own content-type labels (Xingtu content themes, Juxing content types).  Kept
    # distinct from `creator_type_label` and `industry_labels`: those are different dimensions.
    content_theme_labels: list[str] = Field(default_factory=list)
    followers: LibraryMetric
    monthly_deep_users: LibraryMetric
    monthly_connected_users: LibraryMetric
    monthly_follower_growth_rate: LibraryMetric
    interaction_rate: LibraryMetric
    completion_rate: LibraryMetric
    # DATA-02: the five remaining 「商业能力 → 内容数据」 metrics, projected out of the
    # snapshot JSONB. `play_median` is the platform card 「播放量中位数」
    # (`spread.item_rate_metrics.play_mid`), which is NOT the registered top-level
    # `spread.play_median` leaf (see docs/tasks/CD-08.md).
    play_median: LibraryMetric
    average_duration: LibraryMetric
    average_likes: LibraryMetric
    average_comments: LibraryMetric
    average_shares: LibraryMetric
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
    available_scenes: list[CreatorScene] = Field(default_factory=list)
    platform_star_id: str | None = None
    latest_snapshot_id: str | None = None
    mcn_name: str | None = None
    introduction: str | None = None
    # `basic.gender` exactly as the platform stored it (its numeric code).  Only the presentation
    # layer maps a code to a label, and only for codes verified against the live platform (see
    # frontend/src/profile/views.ts).  Read from the same current projection as `introduction`.
    gender: str | None = None
    collected_field_count: int = 0
    failed_field_count: int = 0
    field_sources: dict[str, JsonValue] = Field(default_factory=dict)
    module_statuses: dict[str, str | None] = Field(default_factory=dict)
    # Modules whose latest observation failed and whose data was read back from an older immutable
    # snapshot.  Additive: an empty map means every module comes from the latest snapshot.
    module_fallbacks: dict[str, JsonValue] = Field(default_factory=dict)
    # A presentation-safe, complete profile assembled from the current projection and the latest
    # immutable snapshot.  It deliberately keeps platform field envelopes (status/unit/period).
    profile_payload: dict[str, JsonValue] = Field(default_factory=dict)


class CreatorUpdateStatus(Model):
    """Current manual/scheduled update state for one library creator."""

    creator_id: str
    in_flight_root_task_id: str | None = None
    task_status: TaskStatus | None = None
    task_stage: str | None = None
    last_write_at: datetime | None = None
    last_success_at: datetime | None = None
    last_success_snapshot_id: str | None = None
    next_due_at: datetime | None = None
    tier: str | None = None
    interval_days: int | None = None
    consecutive_failures: int = 0
    last_failure_reason: str | None = None


class CreatorUpdateResponse(Model):
    root_task_id: str
    status: TaskStatus = TaskStatus.QUEUED
    reused: bool = False


class CreatorUpdateTaskSummary(Model):
    """Latest scheduled batch for one update service; counts come from the task payload."""

    root_task_id: str
    state: TaskStatus
    stage: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    failure_reason: str | None = None
    target_count: int = 0
    valid_count: int = 0
    profile_complete_count: int = 0


class CreatorUpdateServiceView(Model):
    """One (platform, creator_scene) scheduled-update service and its observable state.

    ``effective_enabled`` is the only field that claims actual automation: it requires the
    persisted switch, a live scheduler heartbeat and an available contract.  Fields without a
    reliable source stay empty instead of being invented.
    """

    platform: Literal["douyin_xingtu", "kuaishou_juxing"]
    creator_scene: CreatorScene
    enabled: bool
    effective_enabled: bool
    scheduler_alive: bool
    scheduler_last_tick_at: datetime | None = None
    registry_available: bool | None = None
    unavailable_reason: str | None = None
    enrolled_count: int = 0
    due_count: int = 0
    in_flight_count: int = 0
    missing_target_count: int = 0
    next_due_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_task: CreatorUpdateTaskSummary | None = None


class CreatorUpdateServicePage(Model):
    items: list[CreatorUpdateServiceView]
    scheduler_alive: bool
    scheduler_last_tick_at: datetime | None = None
    scheduler_tick_seconds: float | None = None


class CreatorUpdateServicePatch(Model):
    enabled: bool


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


class CreatorVideoObservation(Model):
    """One 「创作能力 → 最新视频表现」 work observation (DATA-02).

    Counts stay platform-native Decimals: no unit, scale or percentage is inferred here.  A field
    the platform never returns keeps `None` and says so in `field_statuses` — a real platform zero
    stays `0`, so "missing" and "zero" are never conflated.
    """

    module_key: Literal["recent_video_performance", "recent_xingtu_video_performance"]
    position: int
    content_id: str | None = None
    platform_item_id: str | None = None
    platform_video_id: str | None = None
    platform_author_id: str | None = None
    title: str | None = None
    subtitle: str | None = None
    published_at: datetime | None = None
    published_raw: str | None = None
    play_count: Decimal | None = None
    like_count: Decimal | None = None
    comment_count: Decimal | None = None
    favorite_count: Decimal | None = None
    share_count: Decimal | None = None
    # The platform's opaque object-store key, and the id of the verified object once it is stored.
    cover_source_uri: str | None = None
    cover_object_id: str | None = None
    cover_status: Literal["STORED", "UNRESOLVED", "NOT_PROVIDED"] = "NOT_PROVIDED"
    work_url: str | None = None
    field_statuses: dict[str, str] = Field(default_factory=dict)
    observed_at: datetime


class CreatorVideoPage(Model):
    """The ordered work observations of exactly one snapshot."""

    creator_id: str
    snapshot_id: str | None = None
    view_kind: Literal["published", "unavailable"] = "published"
    items: list[CreatorVideoObservation] = Field(default_factory=list)


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

    platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu"
    contract_version: str
    modules: list[ProfileModuleCatalog]
