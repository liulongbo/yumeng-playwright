from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CollectorError(Exception):
    def __init__(self, code: str, reason: str = ""):
        self.code, self.reason = code, reason
        self.diagnostics: list[Any] = []
        super().__init__(f"{code}: {reason}")


# Appendix B public error codes. Platform contracts may only map business states onto these.
ERROR_CODES = frozenset(
    {
        "INVALID_FORM",
        "UNSUPPORTED_FILTER",
        "AI_PARSE_FAILED",
        "PLATFORM_CONDITION_MISMATCH",
        "PLATFORM_PAGE_CHANGED",
        "PLATFORM_RATE_LIMITED",
        "PLATFORM_PERMISSION_DENIED",
        "PLATFORM_QUOTA_EXHAUSTED",
        "SEARCH_CAPABILITY_LIMIT",
        "ACCOUNT_LOGIN_REQUIRED",
        "ACCOUNT_MISMATCH",
        "SESSION_INDETERMINATE",
        "PLATFORM_SECURITY_CHALLENGE",
        "SECURITY_CHALLENGE_LIMIT",
        "SECURITY_CHALLENGE_TIMEOUT",
        "SECURITY_CHALLENGE_SESSION_INVALID",
        "SECURITY_CHALLENGE_ACCOUNT_MISMATCH",
        "SECURITY_CHALLENGE_UNKNOWN",
        "RESOURCE_UNAVAILABLE",
        "LEASE_LOST",
        "CREATOR_INVALID",
        "MODULE_COLLECTION_FAILED",
        "FEATURED_COLLECTION_INCOMPLETE",
        "COVER_STORE_FAILED",
        "STORAGE_UNAVAILABLE",
        "BUDGET_EXHAUSTED",
        "TASK_CANCELLED",
    }
)


class FieldStatus(StrEnum):
    COLLECTED = "COLLECTED"
    NOT_PROVIDED = "NOT_PROVIDED"
    NO_PERMISSION = "NO_PERMISSION"
    NO_DATA = "NO_DATA"
    FAILED = "FAILED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class TaskStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PARSING = "PARSING"
    QUEUED = "QUEUED"
    SEARCHING = "SEARCHING"
    COLLECTING = "COLLECTING"
    PERSISTING = "PERSISTING"
    RETRY_WAIT = "RETRY_WAIT"
    WAITING_FOR_LOGIN = "WAITING_FOR_LOGIN"
    WAITING_FOR_ACCOUNT = "WAITING_FOR_ACCOUNT"
    WAITING_FOR_VERIFICATION = "WAITING_FOR_VERIFICATION"
    WAITING_FOR_RESOURCE = "WAITING_FOR_RESOURCE"
    PAUSED_BUDGET = "PAUSED_BUDGET"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    PARTIAL_COMPLETED = "PARTIAL_COMPLETED"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    FAILED = "FAILED"


class NetworkMode(StrEnum):
    """Explicit network binding. A local development unit is never a production line unit."""

    PRODUCTION_LINE = "production_line"
    LOCAL_DEVELOPMENT = "local_development"


class SessionHealthStatus(StrEnum):
    """Observed platform-session state for the current browser process.

    A persisted execution-unit state is never accepted as proof of a live session.  Only a
    current observation can produce ``VALID``.
    """

    VALID = "VALID"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    SECURITY_CHALLENGE = "SECURITY_CHALLENGE"
    INDETERMINATE = "INDETERMINATE"


class ReleaseDisposition(StrEnum):
    VERIFIED_READY = "VERIFIED_READY"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    SECURITY_CHALLENGE = "SECURITY_CHALLENGE"
    SESSION_UNVERIFIED = "SESSION_UNVERIFIED"
    BROWSER_UNCONFIRMED = "BROWSER_UNCONFIRMED"


class ChallengeType(StrEnum):
    SLIDER_OR_INTERACTIVE = "SLIDER_OR_INTERACTIVE"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    UNKNOWN_SECURITY_CHALLENGE = "UNKNOWN_SECURITY_CHALLENGE"


class ChallengeState(StrEnum):
    DETECTED = "DETECTED"
    HANDLING = "HANDLING"
    VERIFIED = "VERIFIED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class SessionHealth(Model):
    status: SessionHealthStatus
    expected_account_id: str
    observed_account_id: str | None = None
    protected_page_verified: bool = False
    login_page_verified: bool = False
    challenge_verified: bool = False
    checked_at: datetime = Field(default_factory=utcnow)
    browser_version: str | None = None
    browser_environment_hash: str | None = None
    evidence_reason: str

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.checked_at.tzinfo is None:
            raise ValueError("timezone required")
        if self.status == SessionHealthStatus.VALID:
            if (
                not self.protected_page_verified
                or self.observed_account_id != self.expected_account_id
                or self.login_page_verified
                or self.challenge_verified
            ):
                raise ValueError("valid session requires protected page and matching account")
        if self.status == SessionHealthStatus.ACCOUNT_MISMATCH and (
            not self.protected_page_verified
            or not self.observed_account_id
            or self.observed_account_id == self.expected_account_id
        ):
            raise ValueError("account mismatch requires a different observed account")
        return self


class NumberRange(Model):
    min: Decimal | None = None
    max: Decimal | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        values = [v for v in (self.min, self.max) if v is not None]
        if not values or any(not v.is_finite() or v < 0 for v in values):
            raise ValueError("finite nonnegative bound required")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("reversed range")
        return self


class Filter(Model):
    field: Literal["keyword", "creator_type", "followers", "gender", "region", "quote"]
    operator: Literal["eq", "in", "range"]
    value: str | list[str] | NumberRange
    source_fields: list[str] = Field(min_length=1)
    unit: str | None = None
    currency: str | None = None
    cooperation_form: str | None = None


class Sort(Model):
    key: str = "platform_default"


class FilterPlan(Model):
    schema_version: Literal["filter_plan.v1"] = "filter_plan.v1"
    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    capability_version: str
    target_count: int = Field(default=20, ge=1, le=200, strict=True)
    filters: list[Filter] = Field(min_length=1)
    sort: Sort = Field(default_factory=Sort)
    validation_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({f.field for f in self.filters}) != len(self.filters):
            raise ValueError("duplicate filter field")
        if self.validation_errors:
            raise ValueError("plan contains validation errors")
        for f in self.filters:
            if isinstance(f.value, str) and not f.value.strip():
                raise ValueError("empty filter")
            if isinstance(f.value, list) and (not f.value or any(not s.strip() for s in f.value)):
                raise ValueError("empty options")
            if (f.operator == "range") != isinstance(f.value, NumberRange):
                raise ValueError("operator/value mismatch")
            if f.operator == "eq" and not isinstance(f.value, str):
                raise ValueError("eq requires text")
            if f.operator == "in" and not isinstance(f.value, list):
                raise ValueError("in requires options")
            if f.field == "quote" and not (f.currency and f.cooperation_form and f.unit):
                raise ValueError("quote requires currency, cooperation form and unit")
        return self

    def digest(self) -> str:
        # Target is a stop condition, never part of platform request matching.
        data = self.model_dump(mode="json", exclude={"target_count", "validation_errors"})
        data["filters"] = sorted(data["filters"], key=lambda f: f["field"])
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class FilterCapability(Model):
    field: str
    operators: list[str]
    enum: list[str] = Field(default_factory=list)
    unit: str | None = None
    currencies: list[str] = Field(default_factory=list)
    cooperation_forms: list[str] = Field(default_factory=list)
    keyword_mode: Literal["content"] | None = None


class Capabilities(Model):
    version: str
    status: Literal["UNVERIFIED", "VERIFIED", "DISABLED"] = "UNVERIFIED"
    sample_kind: Literal["synthetic", "live"]
    evidence_refs: list[str] = Field(default_factory=list)
    fields: list[FilterCapability] = Field(default_factory=list)
    sorts: list[str] = Field(default_factory=lambda: ["platform_default"])
    # Each allowed combination is explicitly verified (subsets are not inferred).
    combinations: list[list[str]] = Field(default_factory=list)

    def validate_plan(self, plan: FilterPlan, *, live: bool) -> None:
        if self.status != "VERIFIED" or self.version != plan.capability_version:
            raise CollectorError("UNSUPPORTED_FILTER", "capability version is not enabled")
        if live and (self.sample_kind != "live" or not self.evidence_refs):
            raise CollectorError("UNSUPPORTED_FILTER", "live evidence required")
        if plan.sort.key not in self.sorts:
            raise CollectorError("UNSUPPORTED_FILTER", "sort")
        if sorted(f.field for f in plan.filters) not in [sorted(c) for c in self.combinations]:
            raise CollectorError("UNSUPPORTED_FILTER", "unverified combination")
        specs = {f.field: f for f in self.fields}
        for f in plan.filters:
            spec = specs.get(f.field)
            if not spec or f.operator not in spec.operators or f.unit != spec.unit:
                raise CollectorError("UNSUPPORTED_FILTER", f.field)
            if f.field == "keyword" and spec.keyword_mode != "content":
                raise CollectorError("UNSUPPORTED_FILTER", "content mode not verified")
            vals = f.value if isinstance(f.value, list) else [f.value]
            if spec.enum and any(v not in spec.enum for v in vals):
                raise CollectorError("UNSUPPORTED_FILTER", "enum")
            if f.field == "followers" and isinstance(f.value, NumberRange):
                if any(v != v.to_integral() for v in (f.value.min, f.value.max) if v is not None):
                    raise CollectorError("INVALID_FORM", "fractional followers")
            if f.field == "quote" and (
                f.currency not in spec.currencies
                or f.cooperation_form not in spec.cooperation_forms
            ):
                raise CollectorError("UNSUPPORTED_FILTER", "quote semantics")


class CreatorRef(Model):
    platform: Literal["douyin_xingtu"] = "douyin_xingtu"
    platform_creator_id: str = Field(min_length=1)
    verified_homepage: str
    first_position: int = Field(default=0, ge=0)
    source_refs: list[str] = Field(default_factory=list)
    creator_id: str | None = None


class CandidateDiagnostic(Model):
    """Unusable search row kept for diagnosis; never counted as a valid creator."""

    reason: Literal["CANDIDATE_IDENTITY_UNREADABLE", "UNVERIFIED_HOMEPAGE"]
    detail: str
    source_ref: str
    operation_id: str


class SearchPage(Model):
    candidates: list[CreatorRef]
    current_checkpoint: str | None
    next_checkpoint: str | None
    conditions_digest: str
    search_generation: int
    operation_id: str
    exhausted: bool = False
    exhaustion_evidence_refs: list[str] = Field(default_factory=list)
    # Rows rejected for an unverified identity or homepage are recorded, not merged.
    unidentified: list[CandidateDiagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def endpoint(self) -> Self:
        if self.exhausted and not self.exhaustion_evidence_refs:
            raise ValueError("exhaustion needs evidence")
        if not self.exhausted and self.next_checkpoint is None:
            raise ValueError("nonterminal page needs checkpoint")
        return self


class CollectionType(StrEnum):
    """The only two homepage featured modules this project collects (technical plan §7.1)."""

    EXCELLENT_REACH = "excellent_reach"
    EXCELLENT_SEEDING = "excellent_seeding"


class CollectionStatus(StrEnum):
    """Collection coverage state; every value needs registered evidence, never a guess.

    ``COMPLETE`` means the verified default set was loaded to its end and every collectable
    field resolved. ``INCOMPLETE`` means the load end could not be proven, a field failed, a
    cover failed or a coverage gap remains. ``EMPTY``/``NO_PERMISSION``/``NOT_PROVIDED`` are
    completed checks with a registered reason and are never treated as collected works.
    """

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    EMPTY = "EMPTY"
    NO_PERMISSION = "NO_PERMISSION"
    NOT_PROVIDED = "NOT_PROVIDED"
    FAILED = "FAILED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class CoverStatus(StrEnum):
    STORED = "STORED"
    FAILED = "FAILED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class NumericValue(Model):
    kind: Literal["number"] = "number"
    amount: Decimal
    bound: Literal["exact", "approximate", "lower"] = "exact"
    quantum: Decimal = Decimal(1)


class QuoteValue(Model):
    kind: Literal["quote"] = "quote"
    amount: NumberRange | None = None
    negotiable: bool = False
    currency: str
    cooperation_form: str


class DistributionGroup(Model):
    label: str
    ratio: Decimal = Field(ge=0, le=1)


class DistributionValue(Model):
    kind: Literal["distribution"] = "distribution"
    dimension: str
    groups: list[DistributionGroup]


class StructuredValue(Model):
    """Lossless JSON data whose business semantics are defined by the field contract.

    Platform-native lists/objects such as multiple cooperation offers and interval payloads
    must stay queryable structures rather than being flattened into an unusable text blob.
    """

    kind: Literal["structured"] = "structured"
    data: JsonValue


class FieldObservation(Model):
    field_key: str
    value: (
        str | list[str] | NumericValue | QuoteValue | DistributionValue | StructuredValue | None
    ) = None
    raw_value: str | None = None
    unit: str | None = None
    period_label: str | None = None
    observed_at: datetime = Field(default_factory=utcnow)
    status: FieldStatus
    source_kind: Literal["response", "dom", "api"] | None = None
    source_contract: str | None = None
    path_ref: str | None = None
    precision: int | None = None
    is_approximate: bool = False
    # The platform displayed a shortened value; the raw text is kept and the state is explicit.
    truncated: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    operation_id: str
    session_version: int
    fallback_reason: str | None = None

    @model_validator(mode="after")
    def evidence(self) -> Self:
        if self.observed_at.tzinfo is None:
            raise ValueError("timezone required")
        if self.status == FieldStatus.COLLECTED:
            if self.value is None or not self.source_kind or not self.source_contract:
                raise ValueError("collected value needs provenance")
        elif self.value is not None:
            raise ValueError("non-collected field cannot carry a value")
        if self.status in {FieldStatus.FAILED, FieldStatus.NOT_ATTEMPTED}:
            if not self.failure_reason:
                raise ValueError("failure reason required")
        elif self.status != FieldStatus.COLLECTED and not self.evidence_refs:
            raise ValueError("absence/permission/empty needs evidence")
        if self.truncated and self.status != FieldStatus.COLLECTED:
            raise ValueError("only a collected value can be marked truncated")
        return self


class CoverRef(Model):
    """A stored cover reference. An object id exists only after a verified object write."""

    source_url: str | None = None
    object_id: str | None = None
    checksum: str | None = None
    content_type: str | None = None
    byte_size: int | None = None
    status: CoverStatus = CoverStatus.NOT_ATTEMPTED
    failure_reason: str | None = None

    @model_validator(mode="after")
    def verified_reference(self) -> Self:
        if self.status == CoverStatus.STORED:
            if (
                not self.object_id
                or not self.checksum
                or not self.content_type
                or self.byte_size is None
                or self.byte_size <= 0
                or self.failure_reason
            ):
                raise ValueError("stored cover requires a verified object")
        elif self.object_id is not None:
            raise ValueError("an unverified cover cannot carry an object reference")
        if self.status == CoverStatus.FAILED and not self.failure_reason:
            raise ValueError("failed cover requires a reason")
        if self.byte_size is not None and self.byte_size < 0:
            raise ValueError("negative cover size")
        return self


class FeaturedCard(Model):
    """One card inside a default featured module; identity is never inferred from text."""

    card_id: str = Field(default_factory=uid)
    position: int = Field(ge=0)
    platform_content_id: str | None = None
    canonical_link: str | None = None
    local_key: str | None = None
    # Internal content identity, filled only when the card was persisted with a verified identity.
    content_id: str | None = None
    fields: list[FieldObservation]
    expected_fields: list[str]
    truncated_fields: list[str] = Field(default_factory=list)
    cover: CoverRef | None = None
    # Same-order reloads of one card in one module are counted, never appended twice.
    reload_count: int = Field(default=1, ge=1)
    operation_id: str
    contract_version: str
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        keys = [f.field_key for f in self.fields]
        if len(keys) != len(set(keys)) or set(keys) - set(self.expected_fields):
            raise ValueError("unexpected or duplicate card fields")
        if set(self.truncated_fields) - {f.field_key for f in self.fields if f.truncated}:
            raise ValueError("truncated flag without a truncated field")
        return self

    @property
    def identity_kind(
        self,
    ) -> Literal["platform_content_id", "canonical_link", "local_key", "missing"]:
        if self.platform_content_id:
            return "platform_content_id"
        if self.canonical_link:
            return "canonical_link"
        if self.local_key:
            return "local_key"
        return "missing"

    @property
    def identity_ref(self) -> str | None:
        """Stable identity for cross-module reuse; unresolved local keys never merge modules."""
        return self.platform_content_id or self.canonical_link

    @property
    def complete(self) -> bool:
        return (
            bool(self.expected_fields)
            and set(self.expected_fields) == {f.field_key for f in self.fields}
            and all(
                f.status not in {FieldStatus.FAILED, FieldStatus.NOT_ATTEMPTED} for f in self.fields
            )
        )


class FeaturedCollectionObservation(Model):
    """One default module observation: ordered cards plus coverage and end-of-load evidence."""

    collection_observation_id: str = Field(default_factory=uid)
    creator_ref: CreatorRef
    collection_type: CollectionType
    module_label: str
    page_url: str
    default_period_label: str | None = None
    observed_at: datetime = Field(default_factory=utcnow)
    status: CollectionStatus
    load_complete: bool = False
    cards: list[FeaturedCard] = Field(default_factory=list)
    # Gaps block completeness; notes are explicit non-blocking observations (truncation, …).
    coverage_gaps: list[str] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)
    # Verified stable collection identifier; null until the platform contract registers one.
    set_key: str | None = None
    operation_id: str
    contract_version: str
    failure_reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.observed_at.tzinfo is None:
            raise ValueError("timezone required")
        positions = [c.position for c in self.cards]
        if positions != list(range(len(self.cards))):
            raise ValueError("card positions must be unique and ordered from zero")
        if len({c.card_id for c in self.cards}) != len(self.cards):
            raise ValueError("duplicate card id")
        if self.status == CollectionStatus.COMPLETE:
            if not self.load_complete or self.coverage_gaps or not self.cards:
                raise ValueError("complete collection needs a proven end and no gap")
            if not all(c.complete for c in self.cards):
                raise ValueError("complete collection cannot contain an incomplete card")
        elif self.status in {
            CollectionStatus.EMPTY,
            CollectionStatus.NO_PERMISSION,
            CollectionStatus.NOT_PROVIDED,
        }:
            if self.cards or not self.evidence_refs:
                raise ValueError("module absence needs evidence and no cards")
        elif self.status in {CollectionStatus.FAILED, CollectionStatus.NOT_ATTEMPTED}:
            if not self.failure_reason:
                raise ValueError("unread/未执行 collection needs a reason")
        elif self.coverage_gaps or not self.load_complete:
            if not self.coverage_gaps:
                raise ValueError("incomplete collection needs a stated gap")
        return self

    @property
    def complete(self) -> bool:
        # A registered terminal absence is a completed check, not a collected collection. Failed,
        # unread and endpoint-unknown states remain incomplete.
        return self.status in {
            CollectionStatus.COMPLETE,
            CollectionStatus.EMPTY,
            CollectionStatus.NO_PERMISSION,
            CollectionStatus.NOT_PROVIDED,
        }

    def fingerprint(self) -> str:
        """Ordered identity fingerprint used to decide whether a reload is the same set."""
        payload = [
            {
                "position": card.position,
                "platform_content_id": card.platform_content_id,
                "canonical_link": card.canonical_link,
                "local_key": card.local_key,
            }
            for card in self.cards
        ]
        return hashlib.sha256(
            json.dumps({"status": self.status.value, "cards": payload}, sort_keys=True).encode()
        ).hexdigest()

    def apply_cover_outcomes(self, *, cover_registered: bool) -> FeaturedCollectionObservation:
        """Return a copy folding cover storage outcomes into coverage.

        A failed or un-attempted cover never looks complete, and the copy is re-validated so the
        status and the gap set always stay consistent.
        """
        gaps = [g for g in self.coverage_gaps if not g.startswith("cover_")]
        for card in self.cards:
            if not cover_registered:
                continue
            if card.cover is None or card.cover.status != CoverStatus.STORED:
                state = card.cover.status.value.lower() if card.cover else "not_attempted"
                gaps.append(f"cover_{state}:{card.card_id}")
        return self._derive(gaps)

    def with_gap(self, gap: str) -> FeaturedCollectionObservation:
        """Return a copy carrying one extra non-cover coverage gap."""
        return self._derive([*self.coverage_gaps, gap])

    def _derive(self, gaps: list[str]) -> FeaturedCollectionObservation:
        terminal = {
            CollectionStatus.EMPTY,
            CollectionStatus.NO_PERMISSION,
            CollectionStatus.NOT_PROVIDED,
            CollectionStatus.FAILED,
            CollectionStatus.NOT_ATTEMPTED,
        }
        if self.status in terminal:
            status = self.status
        else:
            readable = bool(self.cards) and all(c.complete for c in self.cards)
            status = (
                CollectionStatus.COMPLETE
                if self.load_complete and not gaps and readable
                else CollectionStatus.INCOMPLETE
            )
        return FeaturedCollectionObservation.model_validate(
            {**self.model_dump(), "coverage_gaps": gaps, "status": status}
        )

    def _settle_status(self) -> None:
        if self.status in {
            CollectionStatus.EMPTY,
            CollectionStatus.NO_PERMISSION,
            CollectionStatus.NOT_PROVIDED,
            CollectionStatus.FAILED,
            CollectionStatus.NOT_ATTEMPTED,
        }:
            return
        readable = bool(self.cards) and all(c.complete for c in self.cards)
        if self.load_complete and not self.coverage_gaps and readable:
            self.status = CollectionStatus.COMPLETE
        else:
            self.status = CollectionStatus.INCOMPLETE


class ModuleObservation(Model):
    module_observation_id: str = Field(default_factory=uid)
    creator_ref: CreatorRef
    module_key: str
    observed_at: datetime = Field(default_factory=utcnow)
    source_period_label: str | None = None
    fields: list[FieldObservation]
    expected_fields: list[str]
    coverage_gaps: list[str] = Field(default_factory=list)
    operation_id: str
    contract_version: str
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_fields(self) -> Self:
        keys = [f.field_key for f in self.fields]
        if len(keys) != len(set(keys)) or set(keys) - set(self.expected_fields):
            raise ValueError("unexpected or duplicate fields")
        return self

    @property
    def complete(self) -> bool:
        return (
            bool(self.expected_fields)
            and not self.coverage_gaps
            and set(self.expected_fields) == {f.field_key for f in self.fields}
            and all(
                f.status not in {FieldStatus.FAILED, FieldStatus.NOT_ATTEMPTED} for f in self.fields
            )
        )

    @property
    def status(self) -> FieldStatus:
        statuses = {f.status for f in self.fields}
        if FieldStatus.COLLECTED in statuses:
            return FieldStatus.COLLECTED
        if len(statuses) == 1:
            return next(iter(statuses))
        return FieldStatus.FAILED if statuses else FieldStatus.NOT_ATTEMPTED


class ProfileDraftRef(Model):
    creator_id: str
    draft_version: int
    module_observation_ids: list[str]
    basic_valid: bool
    complete: bool
    failure_steps: list[str]


class SegmentBudget(Model):
    """Appendix A protective defaults for one execution segment; not a completion SLA."""

    active_seconds: float = Field(default=7200, gt=0)
    candidate_scan_floor: int = Field(default=200, ge=1)
    candidate_scan_multiplier: int = Field(default=5, ge=1)

    def candidate_scan(self, target_count: int) -> int:
        return max(self.candidate_scan_floor, self.candidate_scan_multiplier * target_count)


class ExecutionContext(Model):
    root_task_id: str
    task_id: str
    attempt_id: str
    execution_unit_id: str
    lease_generation: int
    session_version: int
    capability_version: str
    adapter_version: str
    contract_version: str
    network_mode: NetworkMode = NetworkMode.PRODUCTION_LINE
    budget: SegmentBudget = Field(default_factory=SegmentBudget)


class Candidate(Model):
    ref: CreatorRef
    state: Literal["pending", "collecting", "done", "invalid", "failed"] = "pending"
    valid: bool = False
    modules: dict[str, ModuleObservation] = Field(default_factory=dict)
    observation_history: list[ModuleObservation] = Field(default_factory=list)
    # One current observation per default collection type; replaced only by a newer observation.
    collections: dict[str, FeaturedCollectionObservation] = Field(default_factory=dict)
    collection_history: list[FeaturedCollectionObservation] = Field(default_factory=list)
    failure_reason: str | None = None
    retry_count: int = Field(default=0, ge=0)
    snapshot_ids: list[str] = Field(default_factory=list)


class Checkpoint(Model):
    schema_version: Literal["checkpoint.v1"] = "checkpoint.v1"
    conditions_digest: str
    search_generation: int = 0
    cursor: str | None = None
    visited_cursors: list[str | None] = Field(default_factory=list)
    processed_operations: list[str] = Field(default_factory=list)
    exhausted: bool = False
    exhaustion_evidence_refs: list[str] = Field(default_factory=list)
    search_stop_reason: Literal["SEARCH_CAPABILITY_LIMIT"] | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    scanned_ids: list[str] = Field(default_factory=list)
    pending_page: SearchPage | None = None
    diagnostics: list[CandidateDiagnostic] = Field(default_factory=list)
    no_progress_pages: int = 0
    active_seconds: float = 0
    # Only requests correlated by a registered operation; not all browser/network traffic.
    observed_requests: int = Field(default=0, ge=0)
    observed_responses: int = Field(default=0, ge=0)
    navigation_count: int = Field(default=0, ge=0)
    duplicate_request_count: int = Field(default=0, ge=0)
    featured_load_count: int = Field(default=0, ge=0)
    cover_request_count: int = Field(default=0, ge=0)
    module_seconds: dict[str, float] = Field(default_factory=dict)
    failure_counts: dict[str, int] = Field(default_factory=dict)
    rescan_reasons: list[str] = Field(default_factory=list)
    profile_module_keys: list[str] = Field(default_factory=list)
    profile_field_keys: dict[str, list[str]] = Field(default_factory=dict)
    profile_checkpoint_versions: dict[str, int] = Field(default_factory=dict)
    # F06: the two default collections, their card dictionaries and per-module versions.
    featured_collection_types: list[str] = Field(default_factory=list)
    featured_card_fields: dict[str, list[str]] = Field(default_factory=dict)
    featured_checkpoint_versions: dict[str, int] = Field(default_factory=dict)
    # Security-challenge orchestration is checkpointed so Activity retries and Workflow replay do
    # not reset limits or lose the user-visible waiting summary. All fields have v1-safe defaults.
    challenge_count: int = Field(default=0, ge=0)
    challenge_recovery_count: int = Field(default=0, ge=0)
    challenge_recoveries_by_creator: dict[str, int] = Field(default_factory=dict)
    challenge_first_detected_at: datetime | None = None
    challenge_last_detected_at: datetime | None = None
    challenge_wait_started_at: datetime | None = None
    challenge_last_recovered_at: datetime | None = None
    challenge_current_creator: str | None = None
    challenge_type: ChallengeType | None = None
    challenge_state: ChallengeState | None = None
    contract_version: str
    adapter_version: str
    revision: int = 0


class ProfileRequirement(Model):
    """Business scope, independent of the currently implemented platform registry.

    An incomplete inventory is explicit and can never certify a full profile.
    Historical tasks omit this object and keep their registered-scope semantics.
    """

    version: str = Field(min_length=1)
    inventory_verified: bool = False
    modules: dict[str, list[str]] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def verified_inventory(self) -> Self:
        if any(not key.strip() for key in self.modules):
            raise ValueError("requirement module keys must be nonempty")
        for keys in self.modules.values():
            if len(keys) != len(set(keys)) or any(not key.strip() for key in keys):
                raise ValueError("requirement field keys must be unique and nonempty")
        if self.inventory_verified and (
            not self.evidence_refs or any(not keys for keys in self.modules.values())
        ):
            raise ValueError("verified inventory needs fields for every module and evidence")
        return self


class TaskRecord(Model):
    root_task_id: str
    task_id: str
    attempt_id: str
    plan: FilterPlan
    state: TaskStatus = TaskStatus.QUEUED
    version: int = 0
    execution_unit_id: str
    checkpoint: Checkpoint
    failure_reason: str | None = None
    profile_requirement: ProfileRequirement | None = None
    source: Literal["internal_acceptance", "model"] = "internal_acceptance"
    segment: int = 0
    valid_count: int = 0
    profile_complete_count: int = 0
    featured_complete_count: int = 0
    # Overall featured step state across valid creators: attempted-and-complete, attempted-and-
    # incomplete, or never attempted (no verified default collection registered for this run).
    featured_status: Literal["COMPLETED", "PARTIAL_COMPLETED", "NOT_ATTEMPTED"] = "NOT_ATTEMPTED"
    # Complete only when the target is reached and every valid creator's F05 + F06 steps are done.
    pipeline_complete: bool = False
