"""Minimal MCP stdio client for the locally installed Playwright MCP server.

The DSH session did not expose MCP tools, but @playwright/mcp is installed at
~/.local/lib/node_modules/@playwright/mcp and is the same server implementation the project has
used before.  This module speaks the MCP JSON-RPC protocol over stdio so the acceptance run really
goes through Playwright MCP tools (browser_navigate/snapshot/click/type/...), not through the
Playwright Python library.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

NODE = "/usr/local/bin/node"
# The harness runs with HOME=/Users/Longbo while the MCP package belongs to /Users/yaoyao.
# Discover the installed package explicitly (and allow an env override for other machines).
_CLI_CANDIDATES = [
    os.environ.get("PLAYWRIGHT_MCP_CLI", ""),
    "/Users/yaoyao/.local/lib/node_modules/@playwright/mcp/cli.js",
    str(Path.home() / ".local/lib/node_modules/@playwright/mcp/cli.js"),
]
MCP_CLI = next(
    (Path(candidate) for candidate in _CLI_CANDIDATES if candidate and Path(candidate).is_file()),
    Path(_CLI_CANDIDATES[1]),
)


class MCPError(RuntimeError):
    pass


class PlaywrightMCP:
    def __init__(
        self,
        output_dir: Path,
        *,
        headless: bool = True,
        executable_path: str
        | None = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        override_home: bool = True,
        log_path: Path | None = None,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        args = [
            NODE,
            str(MCP_CLI),
            "--browser",
            "chrome",
            "--isolated",
            "--output-dir",
            str(output_dir),
            "--viewport-size",
            "1440x1000",
        ]
        if executable_path:
            args.extend(["--executable-path", executable_path])
        if headless:
            args.append("--headless")
        # The outer harness sandbox blocks Chrome's own sandbox initialization
        # ("sandbox initialization failed: Operation not permitted"); Playwright MCP exposes
        # --no-sandbox for exactly this container/sandbox case and direct Playwright already runs
        # Chrome without its OS sandbox on this machine.
        args.append("--no-sandbox")
        # HOME is /Users/Longbo inside the harness sandbox, but Playwright must only write under
        # the workspace; point its home/cache/browser directories at writable project paths.
        repo = Path(__file__).resolve().parents[2]
        home = repo / ".runtime/mcp-home"
        cache = repo / ".runtime/mcp-cache"
        home.mkdir(parents=True, exist_ok=True)
        cache.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        if override_home:
            env["HOME"] = str(home)
            env["XDG_CACHE_HOME"] = str(cache)
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(repo / ".runtime/browsers")
        self._stderr_log = log_path.open("a", encoding="utf-8") if log_path else None
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._responses: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._next_id = 0
        self._stash: dict[int, dict[str, Any]] = {}
        self.notes: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._responses.put(json.loads(line))
            except json.JSONDecodeError:
                self.notes.append(line[:300])

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            if self._stderr_log:
                self._stderr_log.write(line)
                self._stderr_log.flush()

    def _send(self, message: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def request(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 120
    ) -> Any:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            if request_id in self._stash:
                response = self._stash.pop(request_id)
            else:
                try:
                    response = self._responses.get(timeout=max(0.05, deadline - time.time()))
                except queue.Empty:
                    break
            if response is None:
                raise MCPError("MCP server closed stdout")
            if response.get("id") != request_id:
                if isinstance(response.get("id"), int):
                    self._stash[response["id"]] = response
                continue
            if "error" in response:
                raise MCPError(f"{method}: {response['error']}")
            return response.get("result")
        raise MCPError(f"{method}: timed out after {timeout}s")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "retry01-acceptance", "version": "1.0"},
            },
        )
        self.notify("notifications/initialized")
        return result

    def tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list")
        return list(result.get("tools", []))

    def call(self, name: str, arguments: dict[str, Any] | None = None, timeout: float = 120) -> Any:
        result = self.request(
            "tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout
        )
        if result.get("isError"):
            raise MCPError(f"{name}: {self.text(result)}")
        return result

    @staticmethod
    def text(result: dict[str, Any]) -> str:
        parts = [
            item.get("text", "") for item in result.get("content", []) if item.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part)

    def call_text(
        self, name: str, arguments: dict[str, Any] | None = None, timeout: float = 120
    ) -> str:
        return self.text(self.call(name, arguments, timeout))

    def close(self) -> None:
        try:
            self.call("browser_close", timeout=20)
        except Exception:  # noqa: BLE001 - closing is best effort
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.kill()
        if self._stderr_log:
            self._stderr_log.close()
