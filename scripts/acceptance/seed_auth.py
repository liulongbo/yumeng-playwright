"""Sign the acceptance browser in once, so later MCP runs start from an authenticated session.

Credentials are read from .runtime/qa-credentials.env and are only typed into the real login form;
they are never written to the evidence files.

Usage: .venv/bin/python scripts/acceptance/seed_auth.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.acceptance.mcp_client import PlaywrightMcp  # noqa: E402
from scripts.acceptance.run_acceptance import BASE, evaluate  # noqa: E402


def qa_password() -> str:
    env = pathlib.Path(".runtime/qa-credentials.env").read_text()
    for line in env.splitlines():
        if line.startswith("QA_MEDIA_A_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("QA_MEDIA_A_PASSWORD not found in .runtime/qa-credentials.env")


def main() -> int:
    password = qa_password()
    with PlaywrightMcp() as client:
        client.initialize()
        client.call("browser_navigate", {"url": f"{BASE}/login"}, timeout=120)
        time.sleep(1.5)
        evaluate(
            client,
            f"(() => {{ window.__acceptanceSecret = {json.dumps(password)}; return true; }})()",
        )
        state = evaluate(
            client,
            """(async () => {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          const username = document.querySelector('input[autocomplete="username"]');
          const input = document.querySelector('.password-field input');
          setter.call(username, 'media-a');
          username.dispatchEvent(new Event('input', { bubbles: true }));
          setter.call(input, window.__acceptanceSecret);
          input.dispatchEvent(new Event('input', { bubbles: true }));
          delete window.__acceptanceSecret;
          document.querySelector('.login-button').click();
          for (let i = 0; i < 80; i += 1) {
            await new Promise((resolve) => setTimeout(resolve, 250));
            if (location.pathname.startsWith('/tasks')) break;
          }
          return { path: location.pathname, heading: document.querySelector('h1') && document.querySelector('h1').textContent };
        })()""",
        )
        print("session:", state)
        return 0 if str(state.get("path", "")).startswith("/tasks") else 1


if __name__ == "__main__":
    raise SystemExit(main())
