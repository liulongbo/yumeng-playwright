"""Minimal MCP stdio client for the project's configured Playwright MCP server.

The project has `[mcp_servers.playwright]` in ~/.codex/config.toml, but this session's tool
registry does not expose `mcp__playwright__*` tools, so this script speaks the same MCP stdio
protocol directly to that exact server. It is a transport stand-in, not a different browser
automation stack: the server, Chrome channel and isolated profile come from the project config.

Usage (see the acceptance driver in run_acceptance.py).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Any

# The project pins its own Chromium under .runtime/browsers (see Makefile `setup`). Point the MCP
# server at that directory so the acceptance run uses the project's verified browser build instead
# of a user cache that may not be writable for this session.
DEFAULT_BROWSERS_PATH = "/Users/Longbo/Developer/YUMENG/.runtime/browsers"

# Playwright keeps a small browser-registry marker under $HOME/Library/Caches/ms-playwright. The
# session's real HOME cache is owned by another account and not writable here, so the MCP server
# gets a scratch HOME inside the project runtime directory (also created by .gitignore'd runtime).
DEFAULT_HOME = "/Users/Longbo/Developer/YUMENG/.runtime/acceptance-home"

DEFAULT_PROFILE_DIR = "/Users/Longbo/Developer/YUMENG/.runtime/acceptance-chrome-profile"

# Same server and Chrome channel as ~/.codex/config.toml, plus the two flags this host needs: the
# outer file sandbox denies Chrome's own sandbox and GPU helper process, so the acceptance browser
# runs with --no-sandbox/--disable-gpu. The profile lives in the project runtime directory because
# ~/Library/Application Support/Google/Chrome is not writable for this session.
DEFAULT_COMMAND = [
    "/usr/local/bin/node",
    "/Users/yaoyao/.local/lib/node_modules/@playwright/mcp/cli.js",
    "--browser",
    "chrome",
    "--no-sandbox",
    "--user-data-dir",
    DEFAULT_PROFILE_DIR,
    "--output-dir",
    "/tmp/dsh-playwright-mcp",
]


class McpError(RuntimeError):
    pass


class PlaywrightMcp:
    def __init__(self, command: list[str] | None = None) -> None:
        self.command = command or DEFAULT_COMMAND
        self._next_id = 0
        self._lock = threading.Lock()
        self._pending_result: dict[int, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._wake = threading.Event()
        self.stderr_log: list[str] = []
        environment = dict(os.environ)
        environment.setdefault("PLAYWRIGHT_BROWSERS_PATH", DEFAULT_BROWSERS_PATH)
        environment["HOME"] = DEFAULT_HOME
        self.process = subprocess.Popen(
            self.command,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.process.stdin and self.process.stdout and self.process.stderr
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()

    # --- transport ---------------------------------------------------------------------------
    def _read_stderr(self) -> None:
        assert self.process.stderr
        for line in self.process.stderr:
            self.stderr_log.append(line.rstrip("\n"))

    def _read_loop(self) -> None:
        assert self.process.stdout
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in message:
                self._pending_result[message["id"]] = message
            else:
                self._events.append(message)
            self._wake.set()

    def send(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 60.0
    ) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                payload["params"] = params
            assert self.process.stdin
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        deadline = timeout
        while deadline > 0:
            if self._wake.wait(0.05):
                self._wake.clear()
            if request_id in self._pending_result:
                message = self._pending_result.pop(request_id)
                if "error" in message:
                    raise McpError(f"{method} failed: {message['error']}")
                return message.get("result", {})
            deadline -= 0.05
        raise McpError(f"{method} timed out after {timeout}s")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        assert self.process.stdin
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    # --- protocol ----------------------------------------------------------------------------
    def initialize(self) -> dict[str, Any]:
        result = self.send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dsh-ui01-acceptance", "version": "1.0"},
            },
            timeout=60,
        )
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        return self.send("tools/list", {}, timeout=60).get("tools", [])

    def call(
        self, name: str, arguments: dict[str, Any] | None = None, *, timeout: float = 120.0
    ) -> Any:
        result = self.send(
            "tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout
        )
        if result.get("isError"):
            raise McpError(f"{name} returned an error: {json.dumps(result)[:600]}")
        return result

    def text_of(self, result: dict[str, Any]) -> str:
        parts = [
            item.get("text", "")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part)

    def __enter__(self) -> PlaywrightMcp:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except Exception:  # noqa: BLE001 - best effort shutdown of a scratch browser
            self.process.kill()
