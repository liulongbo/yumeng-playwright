"""Controlled cover download and object storage (technical plan §7.2, §17.1).

Rules implemented here:

- a cover URL is only fetched through the unit's own authenticated browser session, so the bound
  local/production line is reused and there is no independent direct-connection path;
- host, redirect scope, content type, byte size and timeout are limited by the registered
  :class:`CoverSpec`; anything else fails as ``COVER_STORE_FAILED`` instead of being stored;
- an object is written, read back and verified **before** a :class:`CoverRef` may reference it;
- failures keep the card's text and status so a later retry can re-collect the cover;
- objects that no published/current card references are removable by an explicit cleanup call.

The S3 implementation mirrors :class:`S3EvidenceStore` and stays unverified (U09) until an
object-storage environment is exercised.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlsplit

import boto3

from .contracts import CoverSpec
from .domain import CollectorError, CoverRef, CoverStatus, Model
from .repository import Repository


class FetchedCover(Model):
    body: bytes
    content_type: str
    final_url: str
    status_code: int


CoverFetcher = Callable[[str, CoverSpec], Awaitable[FetchedCover]]


class CoverConfig(Model):
    kind: Literal["local", "s3"] = "local"
    endpoint: str | None = None
    bucket: str | None = None
    directory: Path | None = None


class CoverStore(Protocol):
    def put(
        self,
        *,
        root_task_id: str,
        body: bytes,
        content_type: str,
        checksum: str,
        source_url: str,
    ) -> str: ...

    def verify(self, object_id: str) -> None: ...

    def delete(self, object_id: str) -> None: ...


def cover_object_key(root_task_id: str, checksum: str) -> str:
    return f"cover/{root_task_id}/{checksum}"


def _register(
    repository: Repository,
    *,
    object_id: str,
    checksum: str,
    content_type: str,
    byte_size: int,
    source_url: str,
    root_task_id: str,
) -> None:
    with repository.connect() as conn:
        conn.execute(
            """INSERT INTO media_objects(
            object_id,checksum,kind,content_type,byte_size,source_url,root_task_id)
            VALUES(%s,%s,'cover',%s,%s,%s,%s) ON CONFLICT(object_id) DO NOTHING""",
            (object_id, checksum, content_type, byte_size, source_url, root_task_id),
        )


class LocalCoverStore:
    """Filesystem sink for offline and local verification; same verify-before-reference rules."""

    def __init__(self, repository: Repository, directory: Path, allowed_root: Path):
        self.directory = directory.resolve()
        self.allowed_root = allowed_root.resolve()
        if not self.directory.is_relative_to(self.allowed_root):
            raise CollectorError("STORAGE_UNAVAILABLE", "COVER_STORE_OUTSIDE_RUNTIME_ROOT")
        self.repo = repository

    def path(self, object_id: str) -> Path:
        target = (self.directory / object_id).resolve()
        if not target.is_relative_to(self.directory):
            raise CollectorError("STORAGE_UNAVAILABLE", "COVER_OBJECT_PATH_ESCAPE")
        return target

    def put(
        self,
        *,
        root_task_id: str,
        body: bytes,
        content_type: str,
        checksum: str,
        source_url: str,
    ) -> str:
        object_id = cover_object_key(root_task_id, checksum)
        target = self.path(object_id)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        os.chmod(target.parent, 0o700)
        fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
        self.verify(object_id)
        _register(
            self.repo,
            object_id=object_id,
            checksum=checksum,
            content_type=content_type,
            byte_size=len(body),
            source_url=source_url,
            root_task_id=root_task_id,
        )
        return object_id

    def verify(self, object_id: str) -> None:
        target = self.path(object_id)
        if not target.is_file():
            raise CollectorError("STORAGE_UNAVAILABLE", "COVER_OBJECT_MISSING")
        body = target.read_bytes()
        expected = object_id.rsplit("/", 1)[-1]
        if hashlib.sha256(body).hexdigest() != expected:
            target.unlink(missing_ok=True)
            raise CollectorError("STORAGE_UNAVAILABLE", "COVER_OBJECT_VERIFICATION_FAILED")

    def delete(self, object_id: str) -> None:
        self.path(object_id).unlink(missing_ok=True)

    def body(self, object_id: str) -> bytes:
        return self.path(object_id).read_bytes()


class S3CoverStore:
    def __init__(self, repository: Repository, endpoint: str, bucket: str):
        self.client = boto3.client("s3", endpoint_url=endpoint)
        self.bucket, self.repo = bucket, repository

    def put(
        self,
        *,
        root_task_id: str,
        body: bytes,
        content_type: str,
        checksum: str,
        source_url: str,
    ) -> str:
        object_id = cover_object_key(root_task_id, checksum)
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_id,
            Body=body,
            ContentType=content_type,
            Metadata={"sha256": checksum},
        )
        self.verify(object_id)
        _register(
            self.repo,
            object_id=object_id,
            checksum=checksum,
            content_type=content_type,
            byte_size=len(body),
            source_url=source_url,
            root_task_id=root_task_id,
        )
        return object_id

    def verify(self, object_id: str) -> None:
        checksum = object_id.rsplit("/", 1)[-1]
        head = self.client.head_object(Bucket=self.bucket, Key=object_id)
        if (
            head.get("Metadata", {}).get("sha256") != checksum
            or not isinstance(head.get("ContentLength"), int)
            or head["ContentLength"] <= 0
        ):
            raise CollectorError("STORAGE_UNAVAILABLE", "COVER_OBJECT_VERIFICATION_FAILED")

    def delete(self, object_id: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_id)


def build_cover_store(
    config: CoverConfig, repository: Repository, runtime_root: Path
) -> CoverStore:
    if config.kind == "s3":
        if not config.endpoint or not config.bucket:
            raise CollectorError("STORAGE_UNAVAILABLE", "COVER_CONFIG_INCOMPLETE")
        return S3CoverStore(repository, config.endpoint, config.bucket)
    directory = config.directory or (runtime_root / "covers")
    return LocalCoverStore(repository, directory, runtime_root)


class CoverPipeline:
    """Fetch + verify + reference; never references an unverified object."""

    def __init__(self, repository: Repository, store: CoverStore):
        self.repo, self.storage = repository, store

    @staticmethod
    def _check_url(url: str, spec: CoverSpec) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in spec.allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise CollectorError("COVER_STORE_FAILED", "COVER_HOST_NOT_ALLOWED")

    @staticmethod
    def _check_response(fetched: FetchedCover, spec: CoverSpec) -> None:
        parsed = urlsplit(fetched.final_url)
        if parsed.scheme != "https" or parsed.hostname not in spec.allowed_hosts:
            # A redirect must not leave the registered cover scope.
            raise CollectorError("COVER_STORE_FAILED", "COVER_REDIRECT_OUT_OF_SCOPE")
        if fetched.status_code != 200:
            raise CollectorError("COVER_STORE_FAILED", "COVER_STATUS")
        content_type = fetched.content_type.split(";")[0].strip().lower()
        if content_type not in spec.allowed_content_types:
            raise CollectorError("COVER_STORE_FAILED", "COVER_CONTENT_TYPE")
        if not fetched.body:
            raise CollectorError("COVER_STORE_FAILED", "COVER_EMPTY_BODY")
        if len(fetched.body) > spec.max_bytes:
            raise CollectorError("COVER_STORE_FAILED", "COVER_TOO_LARGE")

    async def store(
        self,
        *,
        root_task_id: str,
        source_url: str | None,
        spec: CoverSpec,
        fetch: CoverFetcher,
    ) -> CoverRef:
        if not source_url:
            return CoverRef(status=CoverStatus.NOT_ATTEMPTED, failure_reason="COVER_SOURCE_MISSING")
        try:
            self._check_url(source_url, spec)
            fetched = await fetch(source_url, spec)
            self._check_response(fetched, spec)
            checksum = hashlib.sha256(fetched.body).hexdigest()
            content_type = fetched.content_type.split(";")[0].strip().lower()
            object_id = self.storage.put(
                root_task_id=root_task_id,
                body=fetched.body,
                content_type=content_type,
                checksum=checksum,
                source_url=fetched.final_url,
            )
            self.storage.verify(object_id)
            return CoverRef(
                source_url=fetched.final_url,
                object_id=object_id,
                checksum=checksum,
                content_type=content_type,
                byte_size=len(fetched.body),
                status=CoverStatus.STORED,
            )
        except CollectorError as exc:
            reason = f"{exc.code}:{exc.reason}" if exc.reason else exc.code
            return CoverRef(source_url=source_url, status=CoverStatus.FAILED, failure_reason=reason)

    def cleanup_unreferenced(self) -> list[str]:
        """Delete cover objects that no card of any task references (Appendix A lifecycle)."""
        with self.repo.connect() as conn:
            rows = conn.execute(
                """SELECT object_id FROM media_objects m WHERE m.kind='cover' AND NOT EXISTS (
                SELECT 1 FROM featured_cards c WHERE c.cover_object_id = m.object_id)"""
            ).fetchall()
        removed: list[str] = []
        for row in rows:
            object_id = str(row["object_id"])
            self.storage.delete(object_id)
            with self.repo.connect() as conn:
                conn.execute("DELETE FROM media_objects WHERE object_id=%s", (object_id,))
            removed.append(object_id)
        return removed
