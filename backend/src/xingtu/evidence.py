from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

import boto3
from pydantic import Field

from .domain import CollectorError, Model, NetworkMode, utcnow
from .repository import Repository


class EvidenceSummary(Model):
    """Allowlisted structure only. Never accepts bodies, headers, URLs, cookies or tokens."""

    root_task_id: str
    task_id: str
    attempt_id: str
    execution_unit_id: str
    operation_id: str
    contract_version: str
    source_contract: str
    # Evidence produced by a local development unit is labelled as such and never as a line proof.
    network_mode: NetworkMode = NetworkMode.PRODUCTION_LINE
    kind: Literal["failure", "summary"]
    schema_keys: list[str] = Field(default_factory=list)
    status_code: int | None = None
    failure_reason: str | None = None

    def body(self) -> bytes:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()

    def checksum(self) -> str:
        return hashlib.sha256(self.body()).hexdigest()

    def object_key(self) -> str:
        return f"{self.kind}/{self.root_task_id}/{self.checksum()}.json"


class EvidenceSink(Protocol):
    def save(self, summary: EvidenceSummary) -> str: ...


class EvidenceConfig(Model):
    """Local storage is the offline default; S3-compatible storage is used when configured."""

    kind: Literal["local", "s3"] = "local"
    endpoint: str | None = None
    bucket: str | None = None
    directory: Path | None = None


def _register(repository: Repository, key: str, checksum: str, summary: EvidenceSummary) -> None:
    with repository.connect() as conn:
        conn.execute(
            """INSERT INTO raw_evidence(object_id,checksum,root_task_id,kind,expires_at)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(object_id) DO NOTHING""",
            (
                key,
                checksum,
                summary.root_task_id,
                summary.kind,
                utcnow() + timedelta(days=30 if summary.kind == "failure" else 90),
            ),
        )


class S3EvidenceStore:
    def __init__(self, repository: Repository, endpoint: str, bucket: str):
        # AWS credential resolution comes from environment/credential references, never log it.
        self.client = boto3.client("s3", endpoint_url=endpoint)
        self.bucket, self.repo = bucket, repository

    def save(self, summary: EvidenceSummary) -> str:
        body, checksum = summary.body(), summary.checksum()
        key = summary.object_key()
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            Metadata={"sha256": checksum},
        )
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        if (
            head.get("ContentLength") != len(body)
            or head.get("Metadata", {}).get("sha256") != checksum
        ):
            raise CollectorError("STORAGE_UNAVAILABLE", "OBJECT_VERIFICATION_FAILED")
        _register(self.repo, key, checksum, summary)
        return key


class FileEvidenceStore:
    """Filesystem sink for offline and development verification; same lifecycle as S3."""

    def __init__(self, repository: Repository, directory: Path, allowed_root: Path):
        self.directory = directory.resolve()
        self.allowed_root = allowed_root.resolve()
        if not self.directory.is_relative_to(self.allowed_root):
            raise CollectorError("STORAGE_UNAVAILABLE", "EVIDENCE_OUTSIDE_RUNTIME_ROOT")
        self.repo = repository

    def save(self, summary: EvidenceSummary) -> str:
        body, checksum = summary.body(), summary.checksum()
        target = self.directory / summary.kind / summary.root_task_id / f"{checksum}.json"
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        os.chmod(target.parent, 0o700)
        fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
        written = target.read_bytes()
        if written != body or hashlib.sha256(written).hexdigest() != checksum:
            target.unlink(missing_ok=True)
            raise CollectorError("STORAGE_UNAVAILABLE", "OBJECT_VERIFICATION_FAILED")
        key = summary.object_key()
        _register(self.repo, key, checksum, summary)
        return key


def build_evidence_sink(
    config: EvidenceConfig, repository: Repository, runtime_root: Path
) -> EvidenceSink:
    if config.kind == "s3":
        if not config.endpoint or not config.bucket:
            raise CollectorError("STORAGE_UNAVAILABLE", "EVIDENCE_CONFIG_INCOMPLETE")
        return S3EvidenceStore(repository, config.endpoint, config.bucket)
    directory = config.directory or (runtime_root / "evidence")
    return FileEvidenceStore(repository, directory, runtime_root)


def schema_keys(payload: Any) -> list[str]:
    """Structural key summary only; values and page text are never recorded."""
    if not isinstance(payload, dict):
        return []
    return sorted(str(key) for key in payload)[:32]
