"""The S3 read paths must release the streaming body on every outcome.

botocore returns the pooled HTTP connection only after the response body is closed. Both cover
readers previously called ``response["Body"].read()`` and abandoned the stream, so every request
leaked a connection until the pool was exhausted. These tests pin the release behaviour for the
success path and for a body whose ``read()`` raises.
"""

from __future__ import annotations

import hashlib

import pytest
from xingtu.covers import S3CoverStore
from xingtu.domain import CollectorError
from xingtu.product_covers import ProductCoverConfig, ProductCoverReader

BODY = b"synthetic-cover-bytes"
CHECKSUM = hashlib.sha256(BODY).hexdigest()


class StubBody:
    """Duck-typed stand-in for botocore's StreamingBody."""

    def __init__(self, data: bytes | None = BODY, *, fail: bool = False) -> None:
        self.data = data
        self.fail = fail
        self.close_calls = 0

    def read(self) -> bytes:
        if self.fail:
            raise OSError("synthetic transport failure")
        assert self.data is not None
        return self.data

    def close(self) -> None:
        self.close_calls += 1


class StubS3Client:
    def __init__(self, *, body: StubBody | None = None, metadata: dict[str, str] | None = None):
        self.body = body or StubBody()
        self.metadata = metadata or {}
        self.head_calls = 0

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:  # noqa: N803 - botocore API
        del Bucket, Key
        return {"Body": self.body}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:  # noqa: N803
        del Bucket, Key
        self.head_calls += 1
        return {"Metadata": self.metadata, "ContentLength": len(BODY)}


def product_reader(client: StubS3Client) -> ProductCoverReader:
    config = ProductCoverConfig(kind="s3", endpoint="http://synthetic.invalid", bucket="covers")
    return ProductCoverReader(config, s3_client=client)


def test_product_cover_reader_closes_the_body_after_a_successful_read():
    client = StubS3Client()
    body = product_reader(client).read("cover-1", checksum=CHECKSUM, byte_size=len(BODY))

    assert body == BODY
    assert client.body.close_calls == 1


def test_product_cover_reader_closes_the_body_when_the_read_fails():
    client = StubS3Client(body=StubBody(fail=True))

    with pytest.raises(CollectorError) as raised:
        product_reader(client).read("cover-1", checksum=CHECKSUM, byte_size=len(BODY))

    assert raised.value.code == "STORAGE_UNAVAILABLE"
    assert client.body.close_calls == 1


def test_s3_cover_store_closes_the_body_after_a_successful_read_back():
    client = StubS3Client(metadata={"sha256": CHECKSUM})
    store = S3CoverStore(None, "http://synthetic.invalid", "covers", client=client)

    store.verify(f"covers/{CHECKSUM}")

    assert client.head_calls == 1
    assert client.body.close_calls == 1


def test_s3_cover_store_closes_the_body_when_the_read_back_fails():
    client = StubS3Client(body=StubBody(fail=True))
    store = S3CoverStore(None, "http://synthetic.invalid", "covers", client=client)

    with pytest.raises(CollectorError) as raised:
        store.verify(f"covers/{CHECKSUM}")

    assert raised.value.code == "STORAGE_UNAVAILABLE"
    assert client.body.close_calls == 1
