from __future__ import annotations

import hashlib
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .domain import CollectorError, Model


class ProductCoverConfig(Model):
    kind: Literal["local", "s3"] = "local"
    directory: Path | None = None
    allowed_root: Path | None = None
    endpoint: str | None = None
    bucket: str | None = None


class ProductCoverReader:
    def __init__(self, config: ProductCoverConfig, *, s3_client: Any | None = None):
        self.config = config
        self.s3_client = s3_client
        if config.kind == "local":
            if not config.directory or not config.allowed_root:
                raise CollectorError("STORAGE_UNAVAILABLE", "COVER_READ_CONFIG_INCOMPLETE")
            directory = config.directory.resolve()
            if not directory.is_relative_to(config.allowed_root.resolve()):
                raise CollectorError("STORAGE_UNAVAILABLE", "COVER_STORE_OUTSIDE_RUNTIME_ROOT")
        elif not config.endpoint or not config.bucket:
            raise CollectorError("STORAGE_UNAVAILABLE", "COVER_READ_CONFIG_INCOMPLETE")

    def read(self, object_id: str, *, checksum: str, byte_size: int) -> bytes:
        if self.config.kind == "local":
            assert self.config.directory
            directory = self.config.directory.resolve()
            target = (directory / object_id).resolve()
            if not target.is_relative_to(directory) or not target.is_file():
                raise CollectorError("INVALID_FORM", "COVER_NOT_FOUND")
            body = target.read_bytes()
        else:
            assert self.config.endpoint and self.config.bucket
            client = self.s3_client or boto3.client("s3", endpoint_url=self.config.endpoint)
            try:
                response = client.get_object(Bucket=self.config.bucket, Key=object_id)
                # botocore only returns the pooled HTTP connection once the streaming body has
                # been closed. Without this the reader leaks one connection per cover request
                # until the pool is exhausted and cover loading stalls.
                with closing(response["Body"]) as stream:
                    body = stream.read()
            except (BotoCoreError, ClientError, KeyError, OSError) as exc:
                raise CollectorError("STORAGE_UNAVAILABLE", "COVER_OBJECT_READ_FAILED") from exc
        if len(body) != byte_size or hashlib.sha256(body).hexdigest() != checksum:
            raise CollectorError("STORAGE_UNAVAILABLE", "COVER_OBJECT_VERIFICATION_FAILED")
        return body
