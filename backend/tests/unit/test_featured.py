"""F06 domain, registry-publication and cover-pipeline rules (offline, synthetic)."""

import copy
import hashlib
import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError
from xingtu.adapter import BrowserAdapter
from xingtu.contracts import FieldSpec, PlatformRegistry, SourceSpec
from xingtu.covers import CoverPipeline, FetchedCover, S3CoverStore
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
)
from xingtu.observer import ReplayRequest


def creator():
    return CreatorRef(platform_creator_id="A", verified_homepage="https://synthetic.invalid/a")


def collected(key="title", value="text", **extra):
    return FieldObservation(
        field_key=key,
        value=value,
        raw_value=str(value),
        status=FieldStatus.COLLECTED,
        source_kind="response",
        source_contract="synthetic-v1",
        operation_id="op",
        session_version=1,
        **extra,
    )


def absent(key="title", status=FieldStatus.NOT_PROVIDED):
    return FieldObservation(
        field_key=key,
        status=status,
        evidence_refs=[f"op:{key}"],
        operation_id="op",
        session_version=1,
    )


def failed(key="title"):
    return FieldObservation(
        field_key=key,
        status=FieldStatus.FAILED,
        failure_reason="SYNTHETIC_READ_FAILED",
        operation_id="op",
        session_version=1,
    )


def test_joined_response_source_requires_all_join_paths():
    with pytest.raises(ValidationError, match="join_row_path, join_response_path"):
        SourceSpec(
            kind="response",
            request_key="cover_signs",
            path="mainURL",
            join_row_path="cover_uri",
        )

    source = SourceSpec(
        kind="response",
        request_key="cover_signs",
        path="mainURL",
        join_row_path="cover_uri",
        join_response_path="img.uri",
        join_request_path="uri",
    )
    assert source.join_response_path == "img.uri" and source.join_request_path == "uri"


def test_missing_source_status_requires_a_live_evidence_reference():
    with pytest.raises(ValidationError, match="missing_source_status and missing_source_evidence"):
        FieldSpec(
            key="subtitle",
            name="subtitle",
            kind="text",
            source=SourceSpec(kind="response", request_key="cards", path="subtitle"),
            missing_source_status="NOT_PROVIDED",
        )


def card(position=0, fields=None, *, cover=None, truncated=(), **extra):
    fields = fields if fields is not None else [collected()]
    return FeaturedCard(
        position=position,
        fields=fields,
        expected_fields=[f.field_key for f in fields],
        truncated_fields=sorted(truncated),
        cover=cover,
        operation_id="op",
        contract_version="synthetic-v1",
        **extra,
    )


def observation(status=CollectionStatus.INCOMPLETE, **extra):
    payload = {
        "creator_ref": creator(),
        "collection_type": "excellent_reach",
        "module_label": "synthetic reach",
        "page_url": "https://synthetic.invalid/creator/A",
        "status": status,
        "load_complete": True,
        "operation_id": "op",
        "contract_version": "synthetic-v1",
    }
    payload.update(extra)
    return FeaturedCollectionObservation.model_validate(payload)


def test_complete_requires_proven_end_and_no_gap():
    with pytest.raises(ValidationError, match="proven end"):
        observation(CollectionStatus.COMPLETE, cards=[card()], load_complete=False)
    with pytest.raises(ValidationError, match="no gap"):
        observation(CollectionStatus.COMPLETE, cards=[card()], coverage_gaps=["x"])
    with pytest.raises(ValidationError, match="no gap"):
        observation(CollectionStatus.COMPLETE, cards=[])
    with pytest.raises(ValidationError, match="incomplete card"):
        observation(CollectionStatus.COMPLETE, cards=[card(fields=[failed()])])
    done = observation(CollectionStatus.COMPLETE, cards=[card()])
    assert done.complete and done.status == CollectionStatus.COMPLETE


def test_incomplete_status_needs_a_stated_gap_and_absence_needs_evidence():
    with pytest.raises(ValidationError, match="stated gap"):
        observation(CollectionStatus.INCOMPLETE, cards=[card()], load_complete=False)
    # An unproven load end with a stated gap is the explicit incomplete state.
    unproven = observation(
        CollectionStatus.INCOMPLETE,
        cards=[card()],
        load_complete=False,
        coverage_gaps=["module_load_end_unverified"],
    )
    assert unproven.status == CollectionStatus.INCOMPLETE and not unproven.complete
    with pytest.raises(ValidationError, match="absence needs evidence"):
        observation(CollectionStatus.EMPTY, load_complete=True)
    with pytest.raises(ValidationError, match="absence needs evidence"):
        observation(CollectionStatus.NOT_PROVIDED, evidence_refs=[])
    with pytest.raises(ValidationError, match="needs a reason"):
        observation(CollectionStatus.FAILED)
    empty = observation(CollectionStatus.EMPTY, load_complete=True, evidence_refs=["op:done"])
    assert empty.complete and empty.status == CollectionStatus.EMPTY
    assert (
        observation(CollectionStatus.NO_PERMISSION, evidence_refs=["op:probe"]).status
        == CollectionStatus.NO_PERMISSION
    )


def test_positions_are_unique_and_ordered_from_zero():
    with pytest.raises(ValidationError, match="positions"):
        observation(CollectionStatus.INCOMPLETE, cards=[card(1)], load_complete=False)
    with pytest.raises(ValidationError, match="positions"):
        observation(
            CollectionStatus.INCOMPLETE,
            cards=[card(0), card(0, fields=[collected("title", "other")])],
            load_complete=False,
        )
    two = observation(
        CollectionStatus.INCOMPLETE,
        cards=[card(0), card(1)],
        load_complete=False,
        coverage_gaps=["module_load_end_unverified"],
    )
    assert [c.position for c in two.cards] == [0, 1]


def test_truncation_and_missing_identity_are_explicit():
    truncated = collected("title", "short…", truncated=True)
    assert card(fields=[truncated], truncated=["title"]).truncated_fields == ["title"]
    with pytest.raises(ValidationError, match="truncated flag"):
        card(fields=[collected()], truncated=["title"])
    with pytest.raises(ValidationError, match="only a collected value"):
        FieldObservation(
            field_key="title",
            status=FieldStatus.NO_DATA,
            truncated=True,
            evidence_refs=["op:title"],
            operation_id="op",
            session_version=1,
        )
    missing = card(fields=[absent("title", FieldStatus.NOT_PROVIDED)])
    assert missing.identity_kind == "missing" and missing.identity_ref is None
    local = card(fields=[collected()], local_key="row-3")
    assert local.identity_kind == "local_key" and local.identity_ref is None


def test_fingerprint_tracks_the_ordered_set_only():
    first = observation(
        CollectionStatus.COMPLETE,
        cards=[card(0, platform_content_id="v1"), card(1, platform_content_id="v2")],
    )
    same = observation(
        CollectionStatus.COMPLETE,
        cards=[card(0, platform_content_id="v1"), card(1, platform_content_id="v2")],
    )
    reordered = observation(
        CollectionStatus.COMPLETE,
        cards=[card(0, platform_content_id="v2"), card(1, platform_content_id="v1")],
    )
    shorter = observation(
        CollectionStatus.INCOMPLETE,
        cards=[card(0, platform_content_id="v1")],
        load_complete=False,
        coverage_gaps=["module_load_end_unverified"],
    )
    assert first.fingerprint() == same.fingerprint()
    assert first.fingerprint() != reordered.fingerprint()
    assert first.fingerprint() != shorter.fingerprint()


def test_cover_outcome_never_looks_complete():
    stored = CoverRef(
        source_url="https://cdn.synthetic.invalid/a.png",
        object_id="cover/root/" + "a" * 64,
        checksum="a" * 64,
        content_type="image/png",
        byte_size=10,
        status=CoverStatus.STORED,
    )
    ok = observation(CollectionStatus.COMPLETE, cards=[card(cover=stored)])
    ok = ok.apply_cover_outcomes(cover_registered=True)
    assert ok.status == CollectionStatus.COMPLETE and not ok.coverage_gaps
    failed = observation(
        CollectionStatus.COMPLETE,
        cards=[card(cover=CoverRef(status=CoverStatus.FAILED, failure_reason="x"))],
    )
    failed = failed.apply_cover_outcomes(cover_registered=True)
    assert failed.status == CollectionStatus.INCOMPLETE
    assert failed.coverage_gaps == [f"cover_failed:{failed.cards[0].card_id}"]
    not_attempted = observation(CollectionStatus.COMPLETE, cards=[card(cover=None)])
    not_attempted = not_attempted.apply_cover_outcomes(cover_registered=True)
    assert not_attempted.status == CollectionStatus.INCOMPLETE


def test_cover_reference_requires_a_verified_object():
    with pytest.raises(ValidationError, match="verified object"):
        CoverRef(status=CoverStatus.STORED, source_url="https://cdn.synthetic.invalid/a.png")
    with pytest.raises(ValidationError, match="unverified cover"):
        CoverRef(status=CoverStatus.NOT_ATTEMPTED, object_id="cover/x")
    with pytest.raises(ValidationError, match="requires a reason"):
        CoverRef(status=CoverStatus.FAILED)


def cover_spec():
    from xingtu.contracts import CoverSpec

    return CoverSpec(
        field_key="cover",
        allowed_hosts=["cdn.synthetic.invalid"],
        allowed_content_types=["image/png"],
        max_bytes=64,
        timeout_seconds=1,
        max_redirects=0,
    )


class Store:
    """Minimal object store double; records what the pipeline actually wrote."""

    def __init__(self, *, verify_failure=False):
        self.objects: dict[str, bytes] = {}
        self.verify_failure = verify_failure

    def put(self, *, root_task_id, body, content_type, checksum, source_url, source_key=None):
        object_id = f"cover/{root_task_id}/{checksum}"
        self.objects[object_id] = body
        return object_id

    def verify(self, object_id):
        if self.verify_failure:
            raise CollectorError("STORAGE_UNAVAILABLE", "OBJECT_VERIFICATION_FAILED")

    def delete(self, object_id):
        self.objects.pop(object_id, None)


def fetch_of(
    body=b"png-bytes", content_type="image/png", final="https://cdn.synthetic.invalid/a.png"
):
    async def fetch(url, spec):
        if isinstance(body, Exception):
            raise body
        return FetchedCover(
            body=body, content_type=content_type, final_url=final or url, status_code=200
        )

    return fetch


async def test_cover_pipeline_stores_only_verified_objects():
    store = Store()
    pipeline = CoverPipeline(None, store)
    ref = await pipeline.store(
        root_task_id="root",
        source_url="https://cdn.synthetic.invalid/a.png",
        spec=cover_spec(),
        fetch=fetch_of(),
    )
    assert ref.status == CoverStatus.STORED
    assert ref.object_id == f"cover/root/{hashlib.sha256(b'png-bytes').hexdigest()}"
    assert ref.byte_size == len(b"png-bytes") and ref.content_type == "image/png"
    assert store.objects[ref.object_id] == b"png-bytes"


@pytest.mark.parametrize(
    "url,body,content_type,final,reason",
    [
        ("http://cdn.synthetic.invalid/a.png", b"x", "image/png", None, "COVER_HOST_NOT_ALLOWED"),
        ("https://evil.invalid/a.png", b"x", "image/png", None, "COVER_HOST_NOT_ALLOWED"),
        (
            "https://cdn.synthetic.invalid/a.png",
            b"x",
            "image/png",
            "https://evil.invalid/a.png",
            "COVER_REDIRECT_OUT_OF_SCOPE",
        ),
        ("https://cdn.synthetic.invalid/a.png", b"x", "text/html", None, "COVER_CONTENT_TYPE"),
        ("https://cdn.synthetic.invalid/a.png", b"x" * 65, "image/png", None, "COVER_TOO_LARGE"),
        ("https://cdn.synthetic.invalid/a.png", b"", "image/png", None, "COVER_EMPTY_BODY"),
    ],
)
async def test_cover_pipeline_rejects_out_of_scope_downloads(
    url, body, content_type, final, reason
):
    ref = await CoverPipeline(None, Store()).store(
        root_task_id="root",
        source_url=url,
        spec=cover_spec(),
        fetch=fetch_of(body=body, content_type=content_type, final=final),
    )
    assert ref.status == CoverStatus.FAILED and reason in (ref.failure_reason or "")
    assert ref.object_id is None


async def test_cover_pipeline_keeps_text_and_status_on_failure():
    ref = await CoverPipeline(None, Store(verify_failure=True)).store(
        root_task_id="root",
        source_url="https://cdn.synthetic.invalid/a.png",
        spec=cover_spec(),
        fetch=fetch_of(),
    )
    assert ref.status == CoverStatus.FAILED
    assert "STORAGE_UNAVAILABLE" in (ref.failure_reason or "") and ref.object_id is None
    missing = await CoverPipeline(None, Store()).store(
        root_task_id="root", source_url=None, spec=cover_spec(), fetch=fetch_of()
    )
    assert missing.status == CoverStatus.NOT_ATTEMPTED
    assert missing.failure_reason == "COVER_SOURCE_MISSING"
    transport = await CoverPipeline(None, Store()).store(
        root_task_id="root",
        source_url="https://cdn.synthetic.invalid/a.png",
        spec=cover_spec(),
        fetch=fetch_of(body=CollectorError("MODULE_COLLECTION_FAILED", "FETCH")),
    )
    assert transport.status == CoverStatus.FAILED


def registry_dict(capabilities):
    """Fully-referenced registry with both default collections registered."""

    def dom(selector):
        return {"kind": "dom", "locator": {"selector": selector}}

    def response(path, key="cards", **extra):
        return {"kind": "response", "request_key": key, "path": path, **extra}

    card_fields = [
        {"key": "title", "name": "t", "kind": "text", "source": response("title")},
        {
            "key": "play",
            "name": "p",
            "kind": "number",
            "unit": "count",
            "source": response("play"),
        },
        {
            "key": "platform_content_id",
            "name": "id",
            "kind": "text",
            "source": response("id"),
        },
        {"key": "link", "name": "l", "kind": "text", "source": response("link")},
        {"key": "cover", "name": "c", "kind": "text", "source": response("cover")},
    ]

    def featured(key):
        return {
            "key": key,
            "module_label": f"synthetic {key}",
            "ready": {"selector": "#featured"},
            "requests": [
                {
                    "key": "cards",
                    "method": "GET",
                    "host": "synthetic.invalid",
                    "path": f"/api/{key}",
                    "request_match": {"id": "$creator_id"},
                    "response_match": {"id": "$creator_id"},
                    "success_path": "code",
                    "success_value": "0",
                    "repeats": True,
                    "repeat_result_mode": "all",
                }
            ],
            "result_request_key": "cards",
            "cards_path": "cards",
            "link_hosts": ["synthetic.invalid"],
            "set_key_path": "set_key",
            "load_complete_path": "done",
            "load_complete_value": "true",
            "card_fields": card_fields,
            "cover": {
                "field_key": "cover",
                "allowed_hosts": ["cdn.synthetic.invalid"],
                "allowed_content_types": ["image/png"],
                "max_bytes": 1000,
                "timeout_seconds": 5,
            },
        }

    return {
        "contract_version": "synthetic-v1",
        "adapter_version": "synthetic-v1",
        "status": "VERIFIED",
        "sample_kind": "synthetic",
        "capabilities": capabilities.model_dump(),
        "allowed_hosts": ["synthetic.invalid"],
        "homepage_path_prefixes": ["/creator/"],
        "action_interval_seconds": 0.001,
        "operation_timeout_seconds": 1,
        "response_body_max_bytes": 4096,
        "session": {
            "entry_url": "https://synthetic.invalid/search",
            "account": {"selector": "#account"},
            "protected_ready": {"selector": "#ready"},
            "error_selectors": {},
            "identity": {"selector": "#identity"},
        },
        "search": {
            "entry_url": "https://synthetic.invalid/search",
            "reset_actions": [],
            "apply_actions": [{"kind": "click", "locator": {"selector": "#go"}}],
            "next_actions": [{"kind": "click", "locator": {"selector": "#next"}}],
            "ready": {"selector": "#ready"},
            "readback": {"sort": {"selector": "#sort"}},
            "requests": [
                {
                    "key": "list",
                    "method": "GET",
                    "host": "synthetic.invalid",
                    "path": "/api/search",
                    "request_match": {"sort": "$sort"},
                    "response_match": {"sort": "$sort"},
                    "success_path": "code",
                    "success_value": "0",
                }
            ],
            "result_request_key": "list",
            "candidates_path": "items",
            "id_path": "id",
            "homepage_path": "url",
            "next_path": "next",
            "exhausted_path": "done",
            "exhausted_value": "true",
            "pagination": "page",
        },
        "modules": [
            {
                "key": "basic",
                "basic": True,
                "ready": {"selector": "#identity"},
                "fields": [
                    {
                        "key": "platform_creator_id",
                        "name": "id",
                        "kind": "text",
                        "source": dom("#i"),
                    },
                    {"key": "nickname", "name": "n", "kind": "text", "source": dom("#n")},
                ],
            }
        ],
        "featured": [featured("excellent_reach"), featured("excellent_seeding")],
    }


def test_featured_registry_is_publishable(capabilities):
    PlatformRegistry.model_validate(registry_dict(capabilities)).require_enabled(live=False)


class FakeS3:
    def __init__(self):
        self.bucket_exists = False
        self.created = 0
        self.objects = {}

    def head_bucket(self, *, Bucket):
        if not self.bucket_exists:
            raise ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadBucket",
            )
        return {}

    def create_bucket(self, *, Bucket):
        self.bucket_exists = True
        self.created += 1

    def head_object(self, *, Bucket, Key):
        body, metadata = self.objects[Key]
        return {"ContentLength": len(body), "Metadata": metadata}

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key][0])}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop(Key, None)


class FailingPutS3:
    def put_object(self, **kwargs):
        raise ClientError(
            {"Error": {"Code": "BadGateway"}, "ResponseMetadata": {"HTTPStatusCode": 502}},
            "PutObject",
        )


def test_s3_bucket_initialization_is_idempotent_and_readback_hash_is_verified():
    client = FakeS3()
    store = S3CoverStore(None, "http://synthetic.invalid", "covers", client=client)
    assert store.ensure_bucket() is True
    assert store.ensure_bucket() is False
    assert client.created == 1

    body = b"synthetic cover"
    checksum = hashlib.sha256(body).hexdigest()
    object_id = f"cover/root/{checksum}"
    client.objects[object_id] = (body, {"sha256": checksum})
    store.verify(object_id)
    client.objects[object_id] = (b"tampered", {"sha256": checksum})
    with pytest.raises(CollectorError, match="COVER_OBJECT_VERIFICATION_FAILED"):
        store.verify(object_id)


async def test_s3_write_failure_is_contained_as_a_failed_cover():
    store = S3CoverStore(None, "http://synthetic.invalid", "covers", client=FailingPutS3())
    ref = await CoverPipeline(None, store).store(
        root_task_id="root",
        source_url="https://cdn.synthetic.invalid/a.png",
        spec=cover_spec(),
        fetch=fetch_of(),
    )

    assert ref.status == CoverStatus.FAILED
    assert ref.object_id is None
    assert ref.failure_reason == "STORAGE_UNAVAILABLE:COVER_OBJECT_WRITE_FAILED"


async def test_missing_joined_card_lookup_replays_only_the_registered_get_parameter(capabilities):
    data = registry_dict(capabilities)
    featured = data["featured"][0]
    featured["card_fields"] = copy.deepcopy(featured["card_fields"])
    featured["requests"].append(
        {
            "key": "cover_signs",
            "method": "GET",
            "host": "synthetic.invalid",
            "path": "/api/sign",
            "request_match": {},
            "response_match": {},
            "success_path": "code",
            "success_value": "0",
            "repeats": True,
            "repeat_result_mode": "all",
        }
    )
    cover = next(field for field in featured["card_fields"] if field["key"] == "cover")
    cover["source"] = {
        "kind": "response",
        "request_key": "cover_signs",
        "path": "img.mainURL",
        "join_row_path": "cover",
        "join_response_path": "img.uri",
        "join_request_path": "uri",
    }
    registry = PlatformRegistry.model_validate(data)

    async def guard():
        pass

    class Page:
        def __init__(self):
            self.urls = []

        async def evaluate(self, script, args):
            self.urls.append(args["url"])
            uri = parse_qs(urlsplit(args["url"]).query)["uri"][0]
            return {
                "status": 200,
                "contentType": "application/json",
                "text": json.dumps(
                    {"code": 0, "img": {"uri": uri, "mainURL": f"https://cdn/{uri}"}}
                ),
            }

    page = Page()
    adapter = BrowserAdapter(None, registry, "account", guard, live=False)
    responses = {"cover_signs": [{"code": 0, "img": {"uri": "a", "mainURL": "https://cdn/a"}}]}
    await adapter.complete_joined_card_sources(
        page,
        registry.featured[0],
        [{"cover": "a"}, {"cover": "b"}],
        responses,
        {
            "cover_signs": ReplayRequest(
                url="https://synthetic.invalid/api/sign?uri=a&durationTS=1",
                method="GET",
                body={"uri": "a", "durationTS": "1"},
                headers={},
            )
        },
    )

    assert page.urls == ["https://synthetic.invalid/api/sign?uri=b&durationTS=1"]
    assert [body["img"]["uri"] for body in responses["cover_signs"]] == ["a", "b"]


def _reject_featured(data, mutate):
    mutate(data["featured"])
    registry = PlatformRegistry.model_validate(data)
    return registry


@pytest.mark.parametrize(
    "reason,mutate",
    [
        (
            "MISSING_DEFAULT_FEATURED_COLLECTION",
            lambda f: f.pop(),
        ),
        ("DUPLICATE_FEATURED_COLLECTION", lambda f: f.append(copy.deepcopy(f[0]))),
        ("INCOMPLETE_FEATURED_CONTRACT", lambda f: f[0].update(cards_path="")),
        ("INCOMPLETE_FEATURED_CONTRACT", lambda f: f[0].update(load_complete_value="")),
        ("MISSING_FEATURED_RESULT_REQUEST", lambda f: f[0].update(result_request_key="nope")),
        (
            "DUPLICATE_CARD_FIELD",
            lambda f: f[0]["card_fields"].append(copy.deepcopy(f[0]["card_fields"][0])),
        ),
        (
            "UNDECLARED_SOURCE_REQUEST",
            lambda f: f[0]["card_fields"][0].update(
                source={"kind": "response", "request_key": "other", "path": "title"}
            ),
        ),
        (
            "MISSING_FIELD_UNIT",
            lambda f: f[0]["card_fields"].append(
                {
                    "key": "extra",
                    "name": "x",
                    "kind": "number",
                    "source": {"kind": "response", "request_key": "cards", "path": "x"},
                }
            ),
        ),
        ("MISSING_LINK_FIELD", lambda f: f[0]["card_fields"].pop(3)),
        ("MISSING_LINK_SCOPE", lambda f: f[0].update(link_hosts=[])),
        ("COVER_FIELD_NOT_DECLARED", lambda f: f[0]["cover"].update(field_key="nope")),
        (
            "INVALID_COVER_SCOPE",
            lambda f: f[0]["cover"].update(allowed_hosts=["https://cdn.synthetic.invalid"]),
        ),
        ("INVALID_COVER_CONTENT_TYPE", lambda f: f[0]["cover"].update(allowed_content_types=[""])),
        ("EMPTY_LOCATOR", lambda f: f[0]["ready"].update(selector="")),
        ("INVALID_MODULE_ENTRY", lambda f: f[0].update(entry="http://synthetic.invalid/x")),
        # A featured module entry must stay inside the verified homepage path range.
        (
            "FEATURED_ENTRY_OUTSIDE_HOMEPAGE",
            lambda f: f[0].update(entry="/works/full-list"),
        ),
        (
            "INVALID_REQUEST_CONTRACT",
            lambda f: f[0]["requests"][0].update(host="other.invalid"),
        ),
        (
            "AMBIGUOUS_MODULE_ABSENCE",
            lambda f: f[0].update(
                absence={
                    "probe": {"kind": "response", "request_key": "cards", "path": "state"},
                    "empty_values": ["x"],
                    "permission_values": ["x"],
                }
            ),
        ),
        (
            "FALLBACK_WITHOUT_TRIGGER",
            lambda f: f[0]["card_fields"][0].update(
                fallback={"kind": "dom", "locator": {"selector": "#x"}}
            ),
        ),
    ],
)
def test_unpublishable_featured_registries_are_rejected(capabilities, reason, mutate):
    data = registry_dict(capabilities)
    with pytest.raises(CollectorError, match=reason):
        _reject_featured(data, mutate).require_enabled(live=False)
