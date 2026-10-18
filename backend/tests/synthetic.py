"""Explicitly artificial data and adapter. Not a live Xingtu sample."""

from contextlib import asynccontextmanager

from xingtu.contracts import CoverSpec, FeaturedCollectionSpec, FieldSpec, LocatorSpec, SourceSpec
from xingtu.covers import FetchedCover
from xingtu.domain import (
    CollectionStatus,
    CollectorError,
    CoverRef,
    CoverStatus,
    CreatorRef,
    FeaturedCard,
    FeaturedCollectionObservation,
    FieldObservation,
    FieldStatus,
    ModuleObservation,
    SearchPage,
    uid,
)

# The registered card dictionary used by synthetic featured modules; the real one is null until
# U05 verification.
FEATURED_CARD_FIELDS = ["platform_content_id", "local_key", "link", "title", "play", "cover"]
COVER_HOST = "cdn.synthetic.invalid"


def featured_spec(key: str, *, cover: bool = True, set_key: bool = True) -> FeaturedCollectionSpec:
    def dom(selector):
        return SourceSpec(kind="dom", locator=LocatorSpec(selector=selector))

    def response(path):
        return SourceSpec(kind="response", request_key="cards", path=path)

    fields = [
        FieldSpec(key="title", name="title", kind="text", source=response("title")),
        FieldSpec(
            key="play",
            name="play",
            kind="number",
            unit="count",
            source=response("play"),
            empty_values=["—"],
        ),
        FieldSpec(
            key="platform_content_id",
            name="id",
            kind="text",
            source=response("id"),
            not_provided_values=["none"],
        ),
        FieldSpec(
            key="local_key", name="local", kind="text", source=response("local"), empty_values=[""]
        ),
        FieldSpec(key="link", name="link", kind="text", source=response("link")),
        FieldSpec(
            key="cover", name="cover", kind="text", source=response("cover"), empty_values=[""]
        ),
    ]
    return FeaturedCollectionSpec(
        key=key,
        module_label=f"synthetic {key}",
        ready=LocatorSpec(selector="#featured"),
        requests=[
            {
                "key": "cards",
                "method": "GET",
                "host": "synthetic.invalid",
                "path": f"/api/{key}",
                "request_match": {"id": "$creator_id", "collection": "$collection"},
                "response_match": {"id": "$creator_id", "collection": "$collection"},
                "success_path": "code",
                "success_value": "0",
            }
        ],
        result_request_key="cards",
        cards_path="cards",
        link_hosts=["synthetic.invalid"],
        set_key_path="set_key" if set_key else None,
        load_complete_path="done",
        load_complete_value="true",
        card_fields=fields,
        cover=(
            CoverSpec(
                field_key="cover",
                allowed_hosts=[COVER_HOST],
                allowed_content_types=["image/png"],
                max_bytes=1_000_000,
                timeout_seconds=5,
                max_redirects=0,
            )
            if cover
            else None
        ),
    )


class SyntheticAdapter:
    module_keys = ["basic", "commercial", "fans"]
    module_fields = {
        "basic": ["platform_creator_id", "nickname"],
        "commercial": ["value"],
        "fans": ["value"],
    }
    module_checkpoint_versions = {"basic": 1, "commercial": 1, "fans": 1}

    def __init__(
        self,
        ids=None,
        *,
        page_size=3,
        invalid=(),
        failed_module=None,
        featured=None,
        cover_spec=True,
    ):
        self.ids = ids if ids is not None else ["1", "2", "3"]
        self.page_size = page_size
        self.invalid = set(invalid)
        self.failed_module = failed_module
        self.visits = []
        self.modules = []
        self.prepared = []
        self.cursor_invalid = False
        self.profile_error = None
        self.before_module = None
        self.featured = {key: dict(config) for key, config in (featured or {}).items()}
        self.featured_keys = list(self.featured)
        self.featured_card_fields = {key: list(FEATURED_CARD_FIELDS) for key in self.featured}
        self.featured_checkpoint_versions = {key: 1 for key in self.featured}
        self.featured_specs = {key: featured_spec(key, cover=cover_spec) for key in self.featured}
        self.featured_calls = []
        self.cover_requests = []
        self.session_rechecks = 0

    async def prepare(self, plan, cp, ctx):
        self.prepared.append(cp.cursor)
        if self.cursor_invalid and cp.cursor:
            self.cursor_invalid = False
            return False
        return True

    async def search(self, plan, cp, ctx):
        offset = int(cp.cursor or "0")
        ids = self.ids[offset : offset + self.page_size]
        end = offset + self.page_size >= len(self.ids)
        return SearchPage(
            candidates=[
                CreatorRef(
                    platform_creator_id=i,
                    verified_homepage=f"https://synthetic.invalid/creator/{i}",
                )
                for i in ids
            ],
            current_checkpoint=cp.cursor,
            next_checkpoint=None if end else str(offset + self.page_size),
            conditions_digest=plan.digest(),
            search_generation=cp.search_generation,
            operation_id=uid(),
            exhausted=end,
            exhaustion_evidence_refs=["synthetic:end"] if end else [],
        )

    async def recheck_session(self):
        self.session_rechecks += 1

    @asynccontextmanager
    async def profile(self, creator, ctx):
        self.visits.append(creator.platform_creator_id)
        if self.profile_error:
            error, self.profile_error = self.profile_error, None
            raise error
        if creator.platform_creator_id in self.invalid:
            raise CollectorError("CREATOR_INVALID", "synthetic deleted creator")
        yield

    async def collect_module(self, key, creator, ctx, row_covers=None):
        self.modules.append((creator.platform_creator_id, key))
        if self.before_module:
            self.before_module(key)
        operation = uid()
        keys = ["platform_creator_id", "nickname"] if key == "basic" else ["value"]
        fields = [
            FieldObservation(
                field_key=k,
                value=creator.platform_creator_id
                if k == "platform_creator_id"
                else "synthetic name",
                raw_value="synthetic",
                status=FieldStatus.COLLECTED,
                source_kind="dom",
                source_contract="synthetic-v1",
                operation_id=operation,
                session_version=ctx.session_version,
            )
            for k in keys
        ]
        if key == self.failed_module:
            fields = [
                FieldObservation(
                    field_key=k,
                    status=FieldStatus.FAILED,
                    failure_reason="SYNTHETIC_TIMEOUT",
                    operation_id=operation,
                    session_version=ctx.session_version,
                )
                for k in keys
            ]
        return ModuleObservation(
            creator_ref=creator,
            module_key=key,
            fields=fields,
            expected_fields=keys,
            operation_id=operation,
            contract_version="synthetic-v1",
            source_period_label="synthetic default period",
        )

    async def collect_featured_collections(self, creator, cp, ctx):
        observations = []
        for key, config in self.featured.items():
            self.featured_calls.append((creator.platform_creator_id, key))
            observations.append(self._featured_observation(key, config, creator, ctx))
        return observations

    def _featured_observation(self, key, config, creator, ctx):
        operation = uid()
        if config.get("fail"):
            return FeaturedCollectionObservation(
                creator_ref=creator,
                collection_type=key,
                module_label=f"synthetic {key}",
                page_url=creator.verified_homepage,
                status=CollectionStatus.FAILED,
                operation_id=operation,
                contract_version="synthetic-v1",
                failure_reason=config["fail"],
            )
        if config.get("absence"):
            return FeaturedCollectionObservation(
                creator_ref=creator,
                collection_type=key,
                module_label=f"synthetic {key}",
                page_url=creator.verified_homepage,
                status=CollectionStatus[config["absence"]],
                operation_id=operation,
                contract_version="synthetic-v1",
                evidence_refs=[f"{operation}:synthetic-absence"],
            )
        cards = []
        for index, card in enumerate(config.get("cards", [])):
            fields = []
            for field_key in FEATURED_CARD_FIELDS:
                raw = card.get(field_key)
                if raw is None:
                    fields.append(
                        FieldObservation(
                            field_key=field_key,
                            status=FieldStatus.NOT_PROVIDED,
                            operation_id=operation,
                            session_version=ctx.session_version,
                            evidence_refs=[f"{operation}:{field_key}"],
                        )
                    )
                elif field_key == "play":
                    fields.append(
                        FieldObservation(
                            field_key=field_key,
                            value={"kind": "number", "amount": raw, "bound": "exact", "quantum": 1},
                            raw_value=str(raw),
                            status=FieldStatus.COLLECTED,
                            source_kind="response",
                            source_contract="synthetic-v1",
                            operation_id=operation,
                            session_version=ctx.session_version,
                        )
                    )
                else:
                    fields.append(
                        FieldObservation(
                            field_key=field_key,
                            value=raw,
                            raw_value=raw,
                            status=FieldStatus.COLLECTED,
                            source_kind="response",
                            source_contract="synthetic-v1",
                            operation_id=operation,
                            session_version=ctx.session_version,
                        )
                    )
            cover_field = next(f for f in fields if f.field_key == "cover")
            cover = CoverRef(
                source_url=cover_field.value
                if cover_field.status == FieldStatus.COLLECTED
                else None,
                status=CoverStatus.NOT_ATTEMPTED,
            )
            card_id = card.get("card_id") or uid()
            cards.append(
                FeaturedCard(
                    card_id=card_id,
                    position=index,
                    platform_content_id=card.get("platform_content_id"),
                    canonical_link=card.get("link"),
                    local_key=card.get("local_key"),
                    fields=fields,
                    expected_fields=list(FEATURED_CARD_FIELDS),
                    truncated_fields=list(card.get("truncated_fields", [])),
                    cover=cover,
                    operation_id=operation,
                    contract_version="synthetic-v1",
                )
            )
        load_complete = bool(config.get("load_complete", True))
        gaps = list(config.get("gaps", []))
        if not load_complete:
            gaps.append("module_load_end_unverified")
        observation = FeaturedCollectionObservation(
            creator_ref=creator,
            collection_type=key,
            module_label=f"synthetic {key}",
            page_url=creator.verified_homepage,
            status=CollectionStatus.INCOMPLETE,
            load_complete=load_complete,
            cards=cards,
            coverage_gaps=gaps,
            set_key=config.get("set_key"),
            operation_id=operation,
            contract_version="synthetic-v1",
        )
        observation._settle_status()
        return observation

    async def fetch_cover(self, url, spec):
        self.cover_requests.append(url)
        if "fail" in url:
            raise CollectorError("COVER_STORE_FAILED", "SYNTHETIC_FETCH_FAILED")
        return FetchedCover(
            body=b"\x89PNG\r\n\x1a\n" + url.encode(),
            content_type="image/png",
            final_url=url,
            status_code=200,
        )

    async def close(self):
        pass
