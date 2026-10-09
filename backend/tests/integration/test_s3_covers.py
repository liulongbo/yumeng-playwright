"""Explicit MinIO/S3 cover-store integration; enabled only with a dedicated test endpoint."""

import hashlib
import os
from uuid import uuid4

import pytest
from xingtu.covers import S3CoverStore
from xingtu.domain import CollectorError, uid


@pytest.mark.asyncio
async def test_minio_bucket_write_readback_verification_and_cleanup(repo, plan):
    endpoint = os.environ.get("XINGTU_TEST_S3_ENDPOINT")
    if not endpoint:
        pytest.skip("XINGTU_TEST_S3_ENDPOINT required for explicit MinIO integration")

    bucket = "xingtu-test-" + uuid4().hex
    root = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    store = S3CoverStore(repo, endpoint, bucket)
    try:
        assert store.ensure_bucket() is True
        assert store.ensure_bucket() is False
        body = b"synthetic minio cover"
        checksum = hashlib.sha256(body).hexdigest()
        object_id = store.put(
            root_task_id=root,
            body=body,
            content_type="image/png",
            checksum=checksum,
            source_url="https://cdn.synthetic.invalid/cover.png",
        )
        store.verify(object_id)
        fetched = store.client.get_object(Bucket=bucket, Key=object_id)["Body"].read()
        assert fetched == body
        with repo.connect() as conn:
            row = conn.execute(
                "SELECT checksum,content_type,byte_size FROM media_objects WHERE object_id=%s",
                (object_id,),
            ).fetchone()
        assert row == {"checksum": checksum, "content_type": "image/png", "byte_size": len(body)}

        store.client.put_object(
            Bucket=bucket,
            Key="cover/tampered/not-the-body-hash",
            Body=b"tampered",
            Metadata={"sha256": "not-the-body-hash"},
        )
        with pytest.raises(CollectorError, match="COVER_OBJECT_VERIFICATION_FAILED"):
            store.verify("cover/tampered/not-the-body-hash")
    finally:
        response = store.client.list_objects_v2(Bucket=bucket)
        for item in response.get("Contents", []):
            store.client.delete_object(Bucket=bucket, Key=item["Key"])
        store.client.delete_bucket(Bucket=bucket)
