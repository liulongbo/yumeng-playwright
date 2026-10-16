"""Opt-in, read-only per-request census used for the DIAG-01 diagnosis.

Why this module exists
----------------------
Every request-count figure this project has ever produced (``observed_requests``,
``duplicate_request_count``, the historical "159 关联请求") is an **aggregate counter** scoped to
requests that matched a registered :class:`RequestSpec`.  Nothing anywhere records the traffic
that did not match: static assets, platform telemetry, prefetches, cover CDN reads, or the same
business endpoint being hit again by a *later* operation.  There is no HAR and no per-request
artifact in the repository, so those layers cannot be measured at all from existing evidence.

This module adds exactly that missing observation, and nothing else.

Default OFF
-----------
It is inert unless ``XINGTU_REQUEST_CENSUS`` names an output file.  ``BrowserRuntime.open()``
consults :func:`census_path_from_env` and attaches nothing when the variable is unset, so the
default execution path is unchanged.  Removing the single call site in ``runtime.py`` and this
file restores the previous behaviour exactly.

Privacy and bounding
--------------------
* Only method, resource type, host, path, status, duration and a failed-request text are kept.
  Query strings, fragments, headers, cookies, request bodies and response bodies are never
  written.  Paths follow the project's existing ``sanitized_url`` convention.
* A short HMAC of the full URL is stored as ``url_key`` so the same endpoint *with the same
  parameters* can be recognised across operations without revealing the parameter values.
* Records are capped (``XINGTU_REQUEST_CENSUS_MAX_RECORDS``, default 50 000) and the file is
  written ``0600``.  Overflow is reported instead of silently discarding.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Request, Response

logger = logging.getLogger(__name__)

ENV_OUTPUT = "XINGTU_REQUEST_CENSUS"
ENV_LABEL = "XINGTU_REQUEST_CENSUS_LABEL"
ENV_MAX_RECORDS = "XINGTU_REQUEST_CENSUS_MAX_RECORDS"
ENV_HMAC = "XINGTU_DIAGNOSTIC_HMAC_KEY"

DEFAULT_MAX_RECORDS = 50_000
# Small enough that an operator watching the artifact sees progress within a second or two, while
# still batching the file writes. Records are always fully flushed on close().
_FLUSH_EVERY = 8


def census_path_from_env() -> Path | None:
    """Resolved census output path, or ``None`` when the census is disabled."""

    raw = (os.environ.get(ENV_OUTPUT) or "").strip()
    return Path(raw).expanduser() if raw else None


def _max_records_from_env() -> int:
    raw = (os.environ.get(ENV_MAX_RECORDS) or "").strip()
    if not raw:
        return DEFAULT_MAX_RECORDS
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("request census: ignoring non-integer %s", ENV_MAX_RECORDS)
        return DEFAULT_MAX_RECORDS


def _resolve_secret() -> tuple[bytes, str]:
    """Stable key when the project already exports one, otherwise a per-run random key."""

    env = (os.environ.get(ENV_HMAC) or "").strip()
    if len(env) >= 16:
        return env.encode(), "XINGTU_DIAGNOSTIC_HMAC_KEY"
    return secrets.token_bytes(32), "per_run_random"


def sanitized_target(url: str) -> tuple[str, str]:
    """Host and path only; query strings and fragments may carry credentials."""

    parsed = urlsplit(url)
    return parsed.hostname or "", parsed.path or "/"


class RequestCensus:
    """Bounded, de-identified per-request recorder attached at BrowserContext level."""

    def __init__(
        self,
        path: Path,
        *,
        label: str | None = None,
        max_records: int | None = None,
    ) -> None:
        self.path = path
        self.label = label or (os.environ.get(ENV_LABEL) or "").strip() or "unlabelled"
        self.max_records = max_records if max_records is not None else _max_records_from_env()
        self.secret, self.secret_source = _resolve_secret()
        self.started_at = datetime.now(UTC)
        self.seq = 0
        self.written = 0
        self.dropped = 0
        self._pending: dict[Request, float] = {}
        self._buffer: list[str] = []
        self._closed = False
        self._context: BrowserContext | None = None

    # -- lifecycle ---------------------------------------------------------------------------

    def attach(self, context: BrowserContext) -> None:
        self._context = context
        context.on("request", self._on_request)
        context.on("response", self._on_response)
        context.on("requestfailed", self._on_request_failed)
        self._emit(
            {
                "kind": "census_header",
                "label": self.label,
                "started_at": self.started_at.isoformat(),
                "max_records": self.max_records,
                "secret_source": self.secret_source,
                "note": (
                    "read-only census; method/resource_type/host/path/status/duration only; "
                    "query strings, headers, cookies and bodies are never recorded"
                ),
            }
        )
        logger.info("request census attached -> %s (label=%s)", self.path, self.label)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Requests that never produced a response or a failure (aborted mid-flight) are still
        # part of the observed traffic, so they are recorded rather than silently lost.
        for request, started in list(self._pending.items()):
            self._emit(self._record(request, started, status=None, error="NO_TERMINAL_EVENT"))
        self._pending.clear()
        if self._context is not None:
            for event, handler in (
                ("request", self._on_request),
                ("response", self._on_response),
                ("requestfailed", self._on_request_failed),
            ):
                try:
                    self._context.remove_listener(event, handler)
                except Exception:  # noqa: BLE001 - context may already be closed
                    logger.debug("request census: listener %s already detached", event)
            self._context = None
        self._emit(
            {
                "kind": "census_footer",
                "label": self.label,
                "finished_at": datetime.now(UTC).isoformat(),
                "records": self.written,
                "dropped": self.dropped,
                "truncated": self.dropped > 0,
            }
        )
        self._flush()
        logger.info(
            "request census closed: records=%s dropped=%s -> %s",
            self.written,
            self.dropped,
            self.path,
        )

    # -- classification ----------------------------------------------------------------------

    @staticmethod
    def classify(resource_type: str, host: str, path: str) -> str:
        """Structural bucket only.

        The ruleset is deliberately mechanical so the report can state it verbatim and a reader
        can re-derive every number.  Anything that does not match a named bucket stays
        ``unrecognised_third_party`` instead of being guessed into a vendor category.
        """

        if host.endswith("xingtu.cn"):
            if resource_type == "document":
                return "platform_document"
            if resource_type in {"xhr", "fetch"}:
                return "platform_api"
            return "platform_asset"
        if resource_type == "document":
            return "third_party_document"
        if resource_type in {"xhr", "fetch"}:
            return "third_party_api"
        if resource_type == "image":
            return "image_asset"
        if resource_type in {"script", "stylesheet", "font", "media"}:
            return "static_asset"
        return "unrecognised_third_party"

    # -- event handlers ----------------------------------------------------------------------

    def _on_request(self, request: Request) -> None:
        if self._closed:
            return
        try:
            self._pending[request] = _monotonic_ms()
        except Exception:  # noqa: BLE001 - a census must never break collection
            logger.debug("request census: on_request failed", exc_info=True)

    def _on_response(self, response: Response) -> None:
        if self._closed:
            return
        try:
            started = self._pending.pop(response.request, None)
            self._emit(
                self._record(
                    response.request,
                    started,
                    status=response.status,
                    error=None,
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("request census: on_response failed", exc_info=True)

    def _on_request_failed(self, request: Request) -> None:
        if self._closed:
            return
        try:
            started = self._pending.pop(request, None)
            failure = request.failure
            self._emit(
                self._record(
                    request,
                    started,
                    status=None,
                    error=str(failure) if failure else "REQUEST_FAILED",
                )
            )
        except Exception:  # noqa: BLE001
            logger.debug("request census: on_request_failed failed", exc_info=True)

    # -- record plumbing ---------------------------------------------------------------------

    def _record(
        self,
        request: Request,
        started: float | None,
        *,
        status: int | None,
        error: str | None,
    ) -> dict[str, Any]:
        self.seq += 1
        host, path = sanitized_target(request.url)
        resource_type = request.resource_type
        return {
            "seq": self.seq,
            "t": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "method": request.method,
            "rt": resource_type,
            "host": host,
            "path": path,
            "bucket": self.classify(resource_type, host, path),
            "status": status,
            "ms": None if started is None else round(_monotonic_ms() - started, 3),
            "error": error,
            "url_key": hmac.new(self.secret, request.url.encode(), hashlib.sha256).hexdigest()[:16],
        }

    def _emit(self, record: dict[str, Any]) -> None:
        if record.get("kind", "").startswith("census_"):
            self._buffer.append(json.dumps(record, ensure_ascii=False))
            self._flush()
            return
        if self.written >= self.max_records:
            self.dropped += 1
            return
        self.written += 1
        self._buffer.append(json.dumps(record, ensure_ascii=False))
        if len(self._buffer) >= _FLUSH_EVERY:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        payload = "\n".join(self._buffer) + "\n"
        self._buffer.clear()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            created = not self.path.exists()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(payload)
            if created:
                os.chmod(self.path, 0o600)
        except OSError:
            # Observation must never take down a collection run.
            logger.warning("request census: cannot write %s", self.path, exc_info=True)


def _monotonic_ms() -> float:
    import time

    return time.monotonic() * 1000.0
