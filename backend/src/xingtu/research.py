"""Local-development research capture for real platform contract registration.

This module is a **development research** tool, not a collection path:

- it is only usable by an execution unit configured with
  ``network_mode=local_development``;
- it only opens hosts explicitly listed in ``research_allowed_hosts``;
- it records isolated raw captures (request index, DOM outline, optional screenshots) under the
  project-private runtime directory for review, never into `contracts/` or `docs/`;
- the registry that is later authored from these captures must still pass the normal
  ``require_enabled(live=True)`` publication gate, so nothing here can enable an unverified
  capability.

It never records request/response headers, cookies, tokens or response bodies. Only structure
(method/host/path/query keys/JSON key paths) and page outline are written.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import BrowserContext, Page, Response
from playwright.async_api import Error as BrowserError
from pydantic import Field

from .domain import CollectorError, Model
from .runtime import BrowserRuntime, UnitConfig

MAX_RESPONSE_BYTES = 2_000_000
MAX_KEY_PATHS = 600
MAX_KEY_DEPTH = 6

# Scalar leaf values are only retained for key names that describe protocol state or pagination.
SCALAR_ALLOWLIST = re.compile(
    r"(^|_)(code|status|success|errno|error_?code|has_?more|has_?next|is_?end|finished|end|"
    r"total|count|page|page_?size|offset|limit|cursor|next|sort|order|type|scene)($|_)",
    re.IGNORECASE,
)
# ASCII lower-label tokens (platform enum values) are retained; anything else is described by shape.
ENUM_TOKEN = re.compile(r"^[a-z][a-z0-9_.\-]{0,47}$")


def _shape(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return f"bool:{str(value).lower()}"
    if isinstance(value, int):
        return f"int:{len(str(value))}"
    if isinstance(value, float):
        return "float"
    text = str(value)
    if not text:
        return "empty"
    if text.isdigit():
        return f"digits:{len(text)}"
    if ENUM_TOKEN.match(text):
        return text
    return f"str:len={len(text)}"


def _safe_scalar(key: str, value: Any) -> Any:
    """Keep literal protocol values (business code, pagination flag) but shape everything else."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and SCALAR_ALLOWLIST.search(key):
        return value
    if isinstance(value, str) and SCALAR_ALLOWLIST.search(key):
        return (
            value
            if ENUM_TOKEN.match(value) or value.isdigit() or len(value) <= 12
            else _shape(value)
        )
    return _shape(value)


def next_search_payload(observed: dict[str, Any] | None) -> dict[str, Any]:
    """Build the one allowed page-2 research request without mutating the observed request."""
    payload = copy.deepcopy(observed)
    if not payload or not isinstance(payload.get("page_param"), dict):
        raise CollectorError("PLATFORM_PAGE_CHANGED", "SEARCH_REQUEST_NOT_OBSERVED")
    if str(payload["page_param"].get("page")) != "1":
        raise CollectorError("PLATFORM_PAGE_CHANGED", "SEARCH_PAGE_ONE_REQUIRED")
    payload["page_param"]["page"] = 2
    return payload


def identity_digest(data: Any) -> dict[str, Any] | None:
    """Non-reversible evidence that two search pages contain distinct creator identities."""
    if not isinstance(data, dict) or not isinstance(data.get("authors"), list):
        return None
    identities = [str(row.get("star_id")) for row in data["authors"] if isinstance(row, dict)]
    if not identities or any(value in {"", "None"} for value in identities):
        return None
    joined = "\n".join(identities).encode()
    return {"count": len(identities), "sha256": hashlib.sha256(joined).hexdigest()}


def bind_matches(
    payload: Any, needle: str, *, _prefix: str = "", _out: list[str] | None = None
) -> list[str]:
    """Key paths whose scalar value equals `needle` (e.g. the id used in the current URL).

    Only dotted key paths are returned, never the value itself.
    """
    if _out is None:
        _out = []
    if len(_out) >= 20 or not needle:
        return _out
    if isinstance(payload, dict):
        for name, value in payload.items():
            bind_matches(
                value, needle, _prefix=f"{_prefix}.{name}" if _prefix else str(name), _out=_out
            )
    elif isinstance(payload, list):
        for index, value in enumerate(payload[:20]):
            bind_matches(value, needle, _prefix=f"{_prefix}[{index}]", _out=_out)
    elif isinstance(payload, (str, int)) and not isinstance(payload, bool):
        if str(payload) == needle:
            _out.append(_prefix)
    return _out


BUSINESS_MESSAGE_PATHS = ("base_resp.status_message", "msg", "message")


def status_message(payload: Any) -> str | None:
    """Bounded platform business message for diagnostics; never page text or user data."""
    for path in BUSINESS_MESSAGE_PATHS:
        value = payload
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return None


def key_paths(
    payload: Any, *, _prefix: str = "", _depth: int = 0, _out: list[str] | None = None
) -> list[str]:
    """Dotted JSON key paths with array markers; values are described by shape only."""
    if _out is None:
        _out = []
    if len(_out) >= MAX_KEY_PATHS or _depth > MAX_KEY_DEPTH:
        return _out
    if isinstance(payload, dict):
        for name, value in payload.items():
            path = f"{_prefix}.{name}" if _prefix else str(name)
            if isinstance(value, dict | list):
                _out.append(path)
                key_paths(value, _prefix=path, _depth=_depth + 1, _out=_out)
            else:
                _out.append(f"{path}={_safe_scalar(str(name), value)}")
    elif isinstance(payload, list):
        marker = f"{_prefix}[]"
        _out.append(f"{marker} (len={len(payload)})")
        if payload:
            key_paths(payload[0], _prefix=marker, _depth=_depth + 1, _out=_out)
    return _out


DOM_OUTLINE_JS = """
() => {
  const MAX_ELEMENTS = 4000;
  const out = [];
  const all = document.querySelectorAll('*');
  for (const el of all) {
    if (out.length >= MAX_ELEMENTS) break;
    const tag = el.tagName.toLowerCase();
    if (tag === 'script' || tag === 'style' || tag === 'noscript' || tag === 'svg') continue;
    const data = {};
    for (const attr of el.attributes) {
      if (attr.name.startsWith('data-')) data[attr.name] = String(attr.value).slice(0, 80);
    }
    const rawText = (el.textContent || '').trim();
    // Small containers (nav items, buttons, labels) keep their label; large ones only a length.
    const leaf = el.children.length <= 2 && rawText.length <= 60;
    out.push({
      tag,
      id: el.id || null,
      cls: el.classList ? Array.from(el.classList).slice(0, 5) : [],
      name: el.getAttribute('name'),
      type: el.getAttribute('type'),
      role: el.getAttribute('role'),
      aria: el.getAttribute('aria-label'),
      title: el.getAttribute('title'),
      placeholder: el.getAttribute('placeholder'),
      href_path: el.getAttribute('href')
        ? String(el.getAttribute('href')).split('?')[0].slice(0, 160) : null,
      value_shape: el.value !== undefined && el.value !== null && el.value !== ''
        ? (String(el.value).length + ' chars') : null,
      scroll: el.scrollHeight > el.clientHeight + 2
        ? { client_height: el.clientHeight, scroll_height: el.scrollHeight,
            scroll_top: el.scrollTop }
        : null,
      text_len: rawText.length,
      text: leaf ? rawText.slice(0, 60) : null,
      data
    });
  }
  return { url_path: location.pathname, elements: out };
}
"""


class ResearchStep(Model):
    action: Literal[
        "goto",
        "wait",
        "wait_for",
        "click",
        "hover",
        "fill",
        "press",
        "scroll",
        "capture",
        "screenshot",
        "fetch_next_search_page",
    ]
    url: str | None = None
    selector: str | None = None
    value: str | None = None
    key: str | None = None
    frame: str | None = None
    state: Literal["visible", "hidden", "attached"] | None = None
    seconds: float | None = Field(default=None, ge=0)
    timeout_seconds: float | None = Field(default=None, gt=0)
    label: str | None = None


class ResearchRecorder:
    """Bounded structural recorder; attaches at context level so every page is covered."""

    def __init__(
        self,
        out_dir: Path,
        *,
        capture_status_message: bool = False,
        bind_check: bool = False,
    ):
        self.out_dir = out_dir
        # Controlled diagnostic: only the platform's own bounded business message scalar.
        self.capture_status_message = capture_status_message
        # Controlled diagnostic: which response key paths carry the id used in the current URL.
        self.bind_check = bind_check
        self.responses: list[dict[str, Any]] = []
        self.seq = 0
        self.mark = 0
        self.pending: set[asyncio.Task[None]] = set()
        self.closed = False
        # Raw request data is held only in memory for the single controlled page-2 experiment.
        # It is never serialized into the research report.
        self.search_request_payload: dict[str, Any] | None = None
        self.search_request_headers: dict[str, str] = {}

    def attach(self, context: BrowserContext) -> None:
        context.on("response", self.on_response)

    def on_response(self, response: Response) -> None:
        if self.closed:
            return
        task = asyncio.create_task(self.record(response))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def record(self, response: Response) -> None:
        try:
            request = response.request
            resource_type = request.resource_type
            if resource_type not in {"xhr", "fetch", "document"}:
                return
            parsed = urlsplit(request.url)
            entry: dict[str, Any] = {
                "seq": self.seq,
                "at": datetime.now(UTC).isoformat(),
                "resource_type": resource_type,
                "method": request.method,
                "host": parsed.hostname,
                "path": parsed.path,
                "query": {key: _shape(values[0]) for key, values in parse_qs(parsed.query).items()},
                "status": response.status,
                "content_type": (response.headers or {}).get("content-type", ""),
            }
            self.seq += 1
            if resource_type == "document":
                entry["body"] = "document (not read)"
                self.responses.append(entry)
                return
            if request.post_data:
                try:
                    body = request.post_data_json
                except (ValueError, json.JSONDecodeError):
                    body = None
                if (
                    request.method == "POST"
                    and parsed.hostname == "www.xingtu.cn"
                    and parsed.path == "/gw/api/gsearch/search_for_author_square"
                    and isinstance(body, dict)
                ):
                    self.search_request_payload = copy.deepcopy(body)
                    all_headers = await request.all_headers()
                    entry["request_header_names"] = sorted(all_headers)
                    forbidden = {
                        "accept-encoding",
                        "connection",
                        "content-length",
                        "cookie",
                        "host",
                        "origin",
                        "referer",
                        "user-agent",
                    }
                    self.search_request_headers = {
                        key: value
                        for key, value in all_headers.items()
                        if key not in forbidden
                        and not key.startswith(":")
                        and not key.startswith("sec-")
                    }
                entry["post_keys"] = (
                    key_paths(body) if isinstance(body, dict) else ["<non-json post body>"]
                )
            length = (response.headers or {}).get("content-length")
            if length and int(length) > MAX_RESPONSE_BYTES:
                entry["body"] = "skipped: too large"
                self.responses.append(entry)
                return
            if "json" not in entry["content_type"].lower():
                entry["body"] = "skipped: not json"
                self.responses.append(entry)
                return
            raw = await response.body()
            if len(raw) > MAX_RESPONSE_BYTES:
                entry["body"] = "skipped: too large"
                self.responses.append(entry)
                return
            data = json.loads(raw)
            entry["keys"] = key_paths(data)
            if parsed.path == "/gw/api/gsearch/search_for_author_square":
                digest = identity_digest(data)
                if digest:
                    entry["identity_digest"] = digest
            if self.capture_status_message:
                message = status_message(data)
                if message is not None:
                    entry["status_message"] = message
            if self.bind_check:
                page_url = response.frame.page.url if response.frame.page else ""
                segment = urlsplit(page_url).path.rstrip("/").rsplit("/", 1)[-1]
                if segment and segment.isdigit():
                    matches = bind_matches(data, segment)
                    if matches:
                        entry["bind_matches"] = matches
            self.responses.append(entry)
        except Exception:
            # Research capture is diagnostic; a single unreadable response is skipped, never
            # reported as a verified observation.
            return

    async def settle(self) -> None:
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)

    async def snapshot(self, page: Page, label: str, screenshots: bool) -> dict[str, Any]:
        await self.settle()
        frames: list[dict[str, Any]] = []
        for frame in page.frames:
            try:
                outline = await frame.evaluate(DOM_OUTLINE_JS)
            except Exception:
                continue
            frame_url = urlsplit(frame.url)
            outline["frame_url_path"] = frame_url.path
            outline["frame_origin"] = f"{frame_url.scheme}://{frame_url.netloc}"
            frames.append(outline)
        new_responses = self.responses[self.mark :]
        self.mark = len(self.responses)
        shot: str | None = None
        if screenshots:
            shot = str(self.out_dir / f"{label}.png")
            try:
                await page.screenshot(path=shot, full_page=False, timeout=15000)
            except BrowserError:
                # A heavy animated page must not discard the structural capture.
                shot = None
        parsed_page = urlsplit(page.url)
        return {
            "label": label,
            "captured_at": datetime.now(UTC).isoformat(),
            "page_origin": f"{parsed_page.scheme}://{parsed_page.netloc}",
            "page_path": parsed_page.path,
            "page_query": {
                key: _shape(values[0]) for key, values in parse_qs(parsed_page.query).items()
            },
            "frames": frames,
            "responses": new_responses,
            "screenshot": shot,
        }

    def finalize(self) -> None:
        self.closed = True

    async def fetch_next_search_page(self, page: Page) -> None:
        """Repeat the observed page-1 search once inside the authenticated page context.

        This is research-only: it does not persist raw request data or enable the production
        direct-request path.  Page 2 is fixed so a malformed step cannot expand the experiment.
        """
        payload = next_search_payload(self.search_request_payload)
        await page.evaluate(
            """
            async ({body, headers}) => {
              const response = await fetch('/gw/api/gsearch/search_for_author_square', {
                method: 'POST',
                credentials: 'include',
                headers: {...headers, 'content-type': 'application/json'},
                body: JSON.stringify(body),
              });
              await response.arrayBuffer();
            }
            """,
            {"body": payload, "headers": self.search_request_headers},
        )


def _require_local(config: UnitConfig, url: str) -> None:
    if not config.is_local_development:
        raise CollectorError("RESOURCE_UNAVAILABLE", "RESEARCH_REQUIRES_LOCAL_DEVELOPMENT_MODE")
    host = urlsplit(url).hostname
    if not host or host not in config.research_allowed_hosts:
        raise CollectorError("PLATFORM_PAGE_CHANGED", "RESEARCH_HOST_NOT_ALLOWED")


async def run_research(
    config: UnitConfig,
    private_root: Path,
    *,
    start_url: str,
    out_dir: Path,
    steps: list[ResearchStep],
    login_wait_seconds: float,
    screenshots: bool,
    login_done_file: Path | None = None,
    capture_status_message: bool = False,
    bind_check: bool = False,
) -> dict[str, Any]:
    _require_local(config, start_url)
    out_dir = out_dir.resolve()
    if not out_dir.is_relative_to(private_root.resolve()):
        raise CollectorError("STORAGE_UNAVAILABLE", "RESEARCH_OUTSIDE_RUNTIME_ROOT")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out_dir, 0o700)

    runtime = BrowserRuntime(config.model_copy(update={"headless": False}), private_root)
    recorder = ResearchRecorder(
        out_dir,
        capture_status_message=capture_status_message,
        bind_check=bind_check,
    )
    report: dict[str, Any] = {
        "network_mode": config.network_mode.value,
        "unit_id": config.unit_id,
        "started_at": datetime.now(UTC).isoformat(),
        "start_url": start_url,
        "login_wait_seconds": login_wait_seconds,
        "steps": [s.model_dump(mode="json") for s in steps],
        "capture_status_message": capture_status_message,
        "bind_check": bind_check,
        "snapshots": [],
        "timeline": [],
    }
    async with runtime.open() as context:
        report["browser_version"] = runtime.browser_version
        report["proxy_configured"] = runtime.proxied
        recorder.attach(context)
        page = context.pages[0] if context.pages else await context.new_page()
        # The platform may open the backend in a new tab; snapshots must follow the newest page.
        current: dict[str, Any] = {"page": page}

        def on_page(created: Page) -> None:
            current["page"] = created
            report["timeline"].append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "event": "new_page",
                    "path": urlsplit(created.url).path,
                }
            )

        context.on("page", on_page)
        await page.goto(start_url, wait_until="domcontentloaded")
        report["timeline"].append(
            {
                "at": datetime.now(UTC).isoformat(),
                "event": "opened",
                "path": urlsplit(page.url).path,
            }
        )
        if login_wait_seconds > 0:
            print(
                f"请在打开的独立浏览器中完成登录/平台验证；最长等待 {int(login_wait_seconds)} 秒。",
                flush=True,
            )
            remaining = login_wait_seconds
            while remaining > 0:
                if login_done_file and login_done_file.exists():
                    print("  收到人工完成信号，提前结束登录窗口。", flush=True)
                    break
                await asyncio.sleep(min(5.0, remaining))
                remaining -= 5.0
                if int(remaining) % 30 == 0:
                    print(f"  剩余约 {max(0, int(remaining))} 秒", flush=True)
        report["timeline"].append(
            {
                "at": datetime.now(UTC).isoformat(),
                "event": "login_window_closed",
                "path": urlsplit(page.url).path,
            }
        )
        for index, step in enumerate(steps):
            label = step.label or f"step{index:02d}-{step.action}"
            print(f"[research] {index}: {step.action} {label}", flush=True)
            page = current["page"]
            if step.action in {"wait", "wait_for", "click", "hover", "fill", "capture"}:
                # Manual maintenance needs the window in front; best effort only.
                with suppress(BrowserError):
                    await page.bring_to_front()
            locator = None
            if step.selector:
                locator = (
                    page.frame_locator(step.frame).locator(step.selector)
                    if step.frame
                    else page.locator(step.selector)
                )
            try:
                if step.action == "goto":
                    assert step.url
                    _require_local(config, step.url)
                    await page.goto(step.url, wait_until="domcontentloaded")
                elif step.action == "wait":
                    await asyncio.sleep(step.seconds or 1.0)
                elif step.action == "wait_for":
                    assert locator
                    await locator.wait_for(
                        state=step.state or "visible", timeout=(step.timeout_seconds or 30) * 1000
                    )
                elif step.action == "click":
                    assert locator
                    await locator.click(timeout=(step.timeout_seconds or 30) * 1000)
                elif step.action == "hover":
                    assert locator
                    await locator.hover(timeout=(step.timeout_seconds or 30) * 1000)
                elif step.action == "fill":
                    assert locator
                    await locator.fill(
                        step.value or "", timeout=(step.timeout_seconds or 30) * 1000
                    )
                elif step.action == "press":
                    assert locator
                    await locator.press(step.key or "Enter")
                elif step.action == "scroll":
                    if locator:
                        await locator.evaluate("(el) => { el.scrollTop += el.clientHeight; }")
                    else:
                        await page.mouse.wheel(0, 1200)
                elif step.action == "screenshot":
                    await page.screenshot(path=str(out_dir / f"{label}.png"))
                elif step.action == "fetch_next_search_page":
                    await recorder.fetch_next_search_page(page)
            except Exception as exc:
                # A failed probe must not discard the observations already collected.
                report.setdefault("step_errors", []).append(
                    {
                        "step": index,
                        "action": step.action,
                        "label": label,
                        "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}",
                    }
                )
                print(f"   step failed: {type(exc).__name__}", flush=True)
                continue
            if step.action in {"capture", "screenshot"} or step.action in {"goto", "click"}:
                try:
                    snapshot = await recorder.snapshot(page, label, screenshots)
                except BrowserError as exc:
                    report.setdefault("step_errors", []).append(
                        {
                            "step": index,
                            "action": "snapshot",
                            "label": label,
                            "error": f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}",
                        }
                    )
                    continue
                report["snapshots"].append({**snapshot, "after_action": step.action})
                report["timeline"].append(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "event": "snapshot",
                        "label": label,
                        "path": snapshot["page_path"],
                        "responses": len(snapshot["responses"]),
                    }
                )
        recorder.finalize()
        (out_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.chmod(out_dir / "report.json", 0o600)
    report["browser_stopped"] = runtime.stopped
    report["finished_at"] = datetime.now(UTC).isoformat()
    # The preliminary report written inside the context preserves observations even if closing
    # fails.  Rewrite it after a confirmed close so the durable evidence also contains isolation
    # state and completion time.
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.chmod(out_dir / "report.json", 0o600)
    return report
