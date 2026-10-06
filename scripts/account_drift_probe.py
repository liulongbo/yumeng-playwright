"""F04/F05 账号漂移检测探针（只读观测：不点击、不登录、不切换账号）。

它回答三个问题
--------------
1. 冷启动后，持久 profile 实际生效的账号是否等于单元绑定的 ``expected_account_id``？
2. 账号是否会在「同一进程内 / 同一页面反复读取 / 换标签页 / 重启 Chrome」之间改变（漂移）？
3. 若改变，哪个 Cookie / localStorage 键在同一步一起改变（载体定位，只比对 HMAC，不出明文）？

为什么这样设计
--------------
现有证据把漂移锁定在「平台侧解析出的当前账号会变」这一层（
``docs/evidence/SESSION-01-acceptance-2026-09-29.md`` 的 H-A 假设：定位器只匹配到 1 个元素，
但内容在两轮之间变化）。因此单次快照不足以判定，必须做**多角度、可重复**的观测，
并区分三种互不相同的现象：

* ``DRIFT_WITHIN_PAGE``    同一页面反复读取就变 → 平台在会话内自行改写
* ``DRIFT_WITHIN_PROCESS`` 同一进程内跨页面/跨标签页变 → 场景或页面级差异
* ``DRIFT_ACROSS_RESTART`` 重启 Chrome 后变 → 与「run 3 → run 4 间隔 3 分钟」同型

已知局限（必须与结论一起引用）
------------------------------
* 探针自身会导航。若平台的「当前账号」是按最近访问解析的，则导航顺序本身可能影响结果，
  所以要把「每轮第一个冷启动观测」作为基线单独看。
* 只读探针**不能**证明变更是平台改写还是外部改写；它只能把范围收敛到载体层。
* ``div.navigator-user__userid`` 匹配 0 或 ≥2 个元素时记为 unreadable（对应已登记缺陷 D1），
  **不等于登出**；探针会额外统计 iframe 内匹配数与页面中出现的不同 ID 数量。
* 账号 ID 按项目既有约定明文记录；Cookie / storage 的**值**只记录 HMAC。

用法
----
# 逻辑自检（不启动浏览器，用合成序列验证判定与载体定位是否正确）
.venv/bin/python scripts/account_drift_probe.py --self-test

# 真实现场观测（会打开 Chrome 窗口；先确认没有 worker 占用该 profile）
XINGTU_DIAGNOSTIC_HMAC_KEY='<32 位以上随机串>' \\
.venv/bin/python scripts/account_drift_probe.py \\
    --config .runtime/units/local-dev-mac-02.json --rounds 2 --gap-seconds 180

# 需要人工登录时：在第 1 轮打开窗口后等待你登录，期间探针不导航
XINGTU_DIAGNOSTIC_HMAC_KEY='<32 位以上随机串>' \\
.venv/bin/python scripts/account_drift_probe.py \\
    --config .runtime/units/local-dev-mac-02.json \\
    --await-login-seconds 600 --rounds 2 --gap-seconds 180

退出码：0=未检出漂移，1=检出漂移，2=不可读/环境错误。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.adapter import BrowserAdapter  # noqa: E402
from xingtu.contracts import PlatformRegistry  # noqa: E402
from xingtu.diagnostics import value_hmac  # noqa: E402
from xingtu.domain import CollectorError  # noqa: E402
from xingtu.runtime import BrowserRuntime, load_unit  # noqa: E402

ACCOUNT_ID_RE = re.compile(r"ID\s*[:：]\s*(\d{6,})")
HREF_RE = re.compile(r'href="([^"]+)"')


def digits_only(value: str) -> str:
    """绑定值形如 ``ID: 1865...``，而页面正文里只有裸数字，比较前必须归一。"""
    return "".join(character for character in str(value) if character.isdigit())


# 只对这些名字的 Cookie 做 HMAC 比对，避免把无关埋点放大成噪声。
CARRIER_HINTS = (
    "session",
    "sid",
    "uid",
    "star",
    "possess",
    "scene",
    "biz",
    "tlb",
    "sso",
    "ticket",
    "auth",
    "staff",
    "csrf",
    "webid",
)

# 平台侧"当前生效账号"最可疑的短生命周期载体，单独高亮。
HIGHLIGHT_CARRIERS = ("possess_scene_star_id", "session_tlb_tag", "has_biz_token", "is_staff_user")

STORAGE_JS = """
() => {
  const dump = (storage) => Object.keys(storage).sort()
    .map((key) => [key, storage.getItem(key)]);
  return {
    origin: location.origin,
    localStorage: dump(localStorage),
    sessionStorage: dump(sessionStorage),
  };
}
"""

VERDICT_EXIT = {
    "STABLE": 0,
    "DRIFT_WITHIN_PAGE": 1,
    "DRIFT_WITHIN_PROCESS": 1,
    "DRIFT_ACROSS_RESTART": 1,
    "IDENTITY_CHANGED_WHILE_UNREADABLE": 1,
    "PERSISTENT_ACCOUNT_MISMATCH": 1,
    "ACCOUNT_UNREADABLE": 2,
    "SESSION_NOT_OBSERVABLE": 2,
}

PROJECT_NETWORK_LAUNCH_ARGS = frozenset(
    {
        "--disable-quic",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    }
)


class ProbeBrowserRuntime(BrowserRuntime):
    """Diagnostic-only browser-launch A/B; never changes the production runtime."""

    def __init__(
        self,
        *args: Any,
        omit_project_network_args: bool = False,
        use_system_keychain: bool = False,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.omit_project_network_args = omit_project_network_args
        self.use_system_keychain = use_system_keychain

    @property
    def launch_args(self) -> list[str]:
        args = super().launch_args
        if not self.omit_project_network_args:
            return args
        return [arg for arg in args if arg not in PROJECT_NETWORK_LAUNCH_ARGS]

    def _launch_options(self) -> dict[str, Any]:
        options = super()._launch_options()
        if self.use_system_keychain:
            # Playwright adds --use-mock-keychain on macOS.  A profile first written by natural
            # Chrome uses the system Keychain; the mock backend cannot decrypt those cookies and
            # Chromium removes the unusable rows.  Ignore only this one default argument, keeping
            # every other Playwright default intact.  This is compatibility A/B, not stealth.
            options["ignore_default_args"] = ["--use-mock-keychain"]
        return options


async def _safe(awaitable: Any, default: Any) -> Any:
    """Diagnostics must never abort the probe; a failed probe is itself a finding."""
    try:
        return await awaitable
    except Exception:  # noqa: BLE001 - diagnostic probe
        return default


async def _safe_bounded(awaitable: Any, default: Any, timeout: float = 3.0) -> Any:
    """Diagnostic read with its own bound so navigation cannot stall report finalization."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except Exception:  # noqa: BLE001 - diagnostic probe
        return default


async def _noop_guard() -> None:
    return None


def derive_index_url(spec: Any) -> str:
    """Protected-page URL from the registered readiness selector, not a guessed constant."""
    match = HREF_RE.search(spec.protected_ready.selector or "")
    if match:
        return "https://www.xingtu.cn" + match.group(1)
    return "https://www.xingtu.cn/ad/creator/index"


async def locator_visible(page: Any, spec: Any) -> bool:
    probe = (
        page.frame_locator(spec.frame).locator(spec.selector)
        if spec.frame
        else page.locator(spec.selector)
    )
    return bool(await _safe(probe.first.is_visible(), False))


async def account_variants(page: Any, selector: str) -> dict[str, Any]:
    """How many elements match, and what each of them says.

    A count other than 1 is the registered D1 symptom, so it is recorded rather than hidden.
    """
    locator = page.locator(selector)
    count = await _safe(locator.count(), -1)
    texts: list[str] = []
    if isinstance(count, int) and count > 0:
        for index in range(min(count, 8)):
            texts.append(((await _safe(locator.nth(index).inner_text(), "")) or "").strip())
    visible = bool(await _safe(locator.first.is_visible(), False)) if count == 1 else False
    return {"count": count, "texts": texts, "visible": visible}


async def account_in_frames(page: Any, selector: str) -> list[dict[str, Any]]:
    """A moved element inside an iframe reproduces D1 without any logout."""
    found: list[dict[str, Any]] = []
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        count = await _safe(frame.locator(selector).count(), 0)
        if isinstance(count, int) and count > 0:
            found.append({"url": frame.url, "count": count})
    return found


async def page_account_ids(page: Any) -> list[str]:
    """Every distinct ``ID: <digits>`` visible in the body.

    More than one distinct id on a single page is direct evidence that the profile/session
    carries several account identities at once (the recorded H-A hypothesis).
    """
    text = await _safe(page.inner_text("body"), "")
    return sorted({match for match in ACCOUNT_ID_RE.findall(text or "")})


async def signal_hmacs(context: Any, page: Any, secret: bytes) -> dict[str, str]:
    """HMAC of every identity-bearing value, so the value never enters the report."""
    signals: dict[str, str] = {}
    cookies = await _safe(context.cookies(), [])
    for cookie in cookies or []:
        name = str(cookie.get("name", ""))
        if not any(hint in name.lower() for hint in CARRIER_HINTS):
            continue
        key = f"cookie:{cookie.get('domain', '')}/{name}"
        signals[key] = value_hmac(secret, str(cookie.get("value", "")))
    storage = await _safe(page.evaluate(STORAGE_JS), None)
    if isinstance(storage, dict) and "xingtu.cn" in str(storage.get("origin", "")):
        for scope in ("localStorage", "sessionStorage"):
            label = "ls" if scope == "localStorage" else "ss"
            for key, value in storage.get(scope) or []:
                signals[f"{label}:{key}"] = value_hmac(secret, str(value or ""))
    return signals


async def observe(
    *,
    context: Any,
    page: Any,
    adapter: BrowserAdapter,
    registry: PlatformRegistry,
    secret: bytes,
    round_index: int,
    sequence: int,
    phase: str,
    health_timeout: float,
    human: bool = False,
) -> dict[str, Any]:
    spec = registry.session
    variants = await account_variants(page, spec.account.selector)
    account = next((text for text in variants["texts"] if text), None)
    health = await _safe(adapter.inspect_session(page, timeout=health_timeout), None)
    challenges = [
        code
        for code, locator_spec in (spec.error_selectors or {}).items()
        if await locator_visible(page, locator_spec)
    ]
    return {
        "round": round_index,
        "sequence": sequence,
        "phase": phase,
        "human_interaction_window": human,
        "observed_at": datetime.now(UTC).isoformat(),
        "url": page.url,
        "final_url": page.url,
        "account": account,
        "account_expected": adapter.account,
        "account_matches_expected": account == adapter.account,
        "account_selector_count": variants["count"],
        "account_selector_texts": variants["texts"],
        "account_selector_visible": variants["visible"],
        "account_in_iframes": await account_in_frames(page, spec.account.selector),
        "distinct_account_ids_in_body": await page_account_ids(page),
        "protected_ready_visible": await _safe(
            page.locator(spec.protected_ready.selector).is_visible(), False
        ),
        "visible_error_states": challenges,
        "session_health": health.model_dump(mode="json") if health else None,
        "signals": await signal_hmacs(context, page, secret),
    }


async def goto(page: Any, url: str) -> None:
    await _safe(page.goto(url, wait_until="domcontentloaded", timeout=45000), None)
    await asyncio.sleep(5)


async def enter_business_page(
    page: Any,
    registry: PlatformRegistry,
    park_urls: list[str],
) -> str | None:
    """已登录时应**立刻进入星图业务页**，而不是停在 SSO 登录页。

    SSO 入口页永远渲染手机号+验证码表单，看到它并不代表未登录；但把窗口停在那里
    既拿不到业务会话（`star_sessionid` 不会被签发），也让人误以为"掉登录了"。
    因此在没有出现安全挑战时，按优先级逐个尝试业务页，返回首个能读到账号的 URL。
    """
    spec = registry.session
    assert spec
    for url in park_urls:
        blocking = [
            code
            for code, locator_spec in (spec.error_selectors or {}).items()
            if await locator_visible(page, locator_spec)
        ]
        if blocking:
            print(f"检测到页面状态 {blocking}，停止自动进入业务页，等待人工处理。")
            return None
        print(f"尝试进入业务页（已登录时应直接看到星图后台首页）：{url}")
        await goto(page, url)
        variants = await account_variants(page, spec.account.selector)
        account = next((text for text in variants["texts"] if text), None)
        if account:
            print(f"业务页已就绪，读到账号：{account}")
            return url
    return None


async def await_manual_login(
    page: Any,
    adapter: BrowserAdapter,
    registry: PlatformRegistry,
    options: argparse.Namespace,
    record: Callable[[Any, str, bool], Awaitable[None]],
    park_urls: list[str] | None = None,
) -> None:
    """人机协同等待：登录期间不导航，但会**主动进入业务页**以建立业务会话。

    停在任何登录页上时，星图业务会话（`star_sessionid`）永远不会被签发，账号也就永远读不到。
    因此先尝试业务页；只有出现安全挑战、或业务页始终读不到账号时，才真正等待人工登录。
    """
    spec = registry.session
    assert spec
    print()
    print("=" * 72)
    print(f"绑定的目标子账号是：{adapter.account}")
    print("如果窗口直接显示星图后台首页，说明已登录，无需任何操作。")
    print(
        f"如果显示登录页，请在这个窗口内人工登录；最多等待 {int(options.await_login_seconds)} 秒。"
    )
    print("=" * 72)
    park_urls = park_urls or []
    if park_urls:
        entered = await enter_business_page(page, registry, park_urls)
        if entered:
            variants = await account_variants(page, spec.account.selector)
            account = next((text for text in variants["texts"] if text), None)
            protected = await _safe(page.locator(spec.protected_ready.selector).is_visible(), False)
            await record(page, "business-page-entered", True)
            if account and protected:
                return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + options.await_login_seconds
    index = 0
    bootstrap_attempts = 0
    while True:
        variants = await account_variants(page, spec.account.selector)
        account = next((text for text in variants["texts"] if text), None)
        protected = await _safe(page.locator(spec.protected_ready.selector).is_visible(), False)
        await record(page, f"human-login[{index}]", True)
        index += 1
        if account:
            print(f"读到账号：{account}（受保护页可见={protected}）")
            if protected:
                return
        blocking = [
            code
            for code, locator_spec in (spec.error_selectors or {}).items()
            if await locator_visible(page, locator_spec)
        ]
        if park_urls and not blocking and bootstrap_attempts < 4:
            target = park_urls[bootstrap_attempts % len(park_urls)]
            bootstrap_attempts += 1
            print(f"未读到账号，重试进入业务页（第 {bootstrap_attempts}/4 次）：{target}")
            await goto(page, target)
            continue
        if loop.time() >= deadline:
            print("等待人工登录超时；后续观测会如实记为不可读。")
            return
        await asyncio.sleep(options.login_poll_seconds)


ACCOUNT_ENTRY_JS = r"""
(args) => {
  const re = new RegExp(args.pattern);
  const all = Array.from(document.querySelectorAll('li,div,span,a,button,p,h1,h2,h3'));
  const matches = [];
  for (const el of all) {
    const text = (el.textContent || '').trim();
    if (!text || text.length > 80) continue;
    if (!re.test(text)) continue;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    matches.push(el);
  }
  const out = [];
  for (const el of matches) {
    let hasMatchingDescendant = false;
    for (const other of matches) {
      if (other !== el && el.contains(other)) { hasMatchingDescendant = true; break; }
    }
    if (hasMatchingDescendant) continue;
    let depth = 0;
    for (let p = el; p; p = p.parentElement) depth += 1;
    const text = (el.textContent || '').trim();
    out.push({
      tag: el.tagName,
      cls: String(el.className || '').slice(0, 120),
      text: text.slice(0, 60),
      digits: (text.match(/\d{6,}/) || [null])[0],
      role: el.getAttribute('role'),
      depth: depth,
    });
    if (out.length >= 40) break;
  }
  return out;
}
"""

ACCOUNT_ANCESTOR_CHAIN_JS = r"""
(args) => {
  const re = new RegExp(args.pattern);
  const all = Array.from(document.querySelectorAll('li,div,span,a,button,p'));
  let target = null;
  for (const el of all) {
    const text = (el.textContent || '').trim();
    if (!text || text.length > 80) continue;
    if (!re.test(text)) continue;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    target = el;
    break;
  }
  if (!target) return {found: false, chain: []};
  const chain = [];
  let node = target;
  for (let level = 0; level < args.levels && node; level += 1) {
    chain.push({
      level: level,
      tag: node.tagName,
      cls: String(node.className || '').slice(0, 140),
      role: node.getAttribute('role'),
      hasHandler: !!(node.onclick),
      childCount: node.children.length,
    });
    node = node.parentElement;
  }
  return {found: true, chain: chain};
}
"""

CLICK_ANCESTOR_JS = r"""
(args) => {
  const re = new RegExp(args.pattern);
  const all = Array.from(document.querySelectorAll('li,div,span,a,button,p'));
  let target = null;
  for (const el of all) {
    const text = (el.textContent || '').trim();
    if (!text || text.length > 80) continue;
    if (!re.test(text)) continue;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    target = el;
    break;
  }
  if (!target) return {clicked: false, reason: 'ACCOUNT_ELEMENT_NOT_FOUND'};
  let node = target;
  for (let i = 0; i < args.level && node.parentElement; i += 1) node = node.parentElement;
  const info = {
    level: args.level,
    tag: node.tagName,
    cls: String(node.className || '').slice(0, 140),
  };
  node.click();
  return {clicked: true, info: info};
}
"""

STORAGE_STRUCTURE_JS = r"""
() => {
  const shape = (value) => {
    if (value === null) return {kind: 'null'};
    if (Array.isArray(value)) {
      const first = value.length ? value[0] : null;
      return {
        kind: 'array',
        length: value.length,
        itemKind: first === null ? 'null' : (Array.isArray(first) ? 'array' : typeof first),
        itemKeys: (first && typeof first === 'object' && !Array.isArray(first))
          ? Object.keys(first).slice(0, 40) : [],
      };
    }
    if (typeof value === 'object') return {kind: 'object', keys: Object.keys(value).slice(0, 60)};
    return {kind: typeof value, length: String(value).length};
  };
  const hint = (raw) => {
    const trimmed = raw.trim();
    if (trimmed.startsWith('{')) return 'json-object';
    if (trimmed.startsWith('[')) return 'json-array';
    if (trimmed.startsWith('"')) return 'json-string';
    if (/^[A-Za-z0-9+/=_-]{16,}$/.test(trimmed)) return 'opaque-token-like';
    return 'plain';
  };
  const parseShape = (raw) => {
    try { return shape(JSON.parse(raw)); } catch (_) { return null; }
  };
  const out = {};
  const scopes = [['localStorage', localStorage], ['sessionStorage', sessionStorage]];
  for (const [scope, storage] of scopes) {
    for (const key of Object.keys(storage)) {
      if (!/STAR|star/.test(key)) continue;
      const raw = storage.getItem(key) || '';
      out[scope + ':' + key] = {
        rawLength: raw.length,
        formatHint: hint(raw),
        json: parseShape(raw),
      };
    }
  }
  return out;
}
"""

SELECT_SUBACCOUNT_JS = r"""
(args) => {
  const digits = args.digits;
  const pattern = args.pattern;
  const re = new RegExp(pattern);
  const all = Array.from(document.querySelectorAll('li,div,span,a,button,p'));
  const matches = [];
  for (const el of all) {
    const text = (el.textContent || '').trim();
    if (!text || text.length > 80) continue;
    if (!re.test(text)) continue;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    matches.push(el);
  }
  const candidates = [];
  for (const el of matches) {
    let hasMatchingDescendant = false;
    for (const other of matches) {
      if (other !== el && el.contains(other)) { hasMatchingDescendant = true; break; }
    }
    if (hasMatchingDescendant) continue;
    const text = (el.textContent || '').trim();
    let depth = 0;
    for (let p = el; p; p = p.parentElement) depth += 1;
    candidates.push({
      el: el,
      depth: depth,
      text: text.slice(0, 60),
      hasTarget: text.includes(digits),
    });
  }
  if (!candidates.length) return {clicked: false, reason: 'NO_ACCOUNT_ENTRY_FOUND'};
  const withTarget = candidates.filter((c) => c.hasTarget);
  if (!withTarget.length) {
    return {
      clicked: false,
      reason: 'TARGET_ID_NOT_PRESENT',
      visibleEntries: candidates.map((c) => c.text),
    };
  }
  withTarget.sort((a, b) => b.depth - a.depth);
  const deepest = withTarget[0];
  let target = deepest.el;
  for (let i = 0; i < 4 && target.parentElement; i += 1) {
    const parent = target.parentElement;
    const cls = String(parent.className || '');
    if (parent.tagName === 'LI' || parent.tagName === 'A' || parent.tagName === 'BUTTON'
        || parent.getAttribute('role') === 'button' || /item|option|account|user|card/i.test(cls)) {
      target = parent;
      break;
    }
    target = parent;
  }
  target.click();
  return {
    clicked: true,
    candidateCount: candidates.length,
    targetTag: target.tagName,
    targetClass: String(target.className || '').slice(0, 120),
    targetText: (target.textContent || '').trim().slice(0, 80),
    deepestText: deepest.text,
  };
}
"""


async def inspect_storage_structure(page: Any) -> dict[str, Any]:
    """只输出存储键的**结构**（长度/格式/JSON 键名），绝不输出任何值。"""
    return await _safe(page.evaluate(STORAGE_STRUCTURE_JS), {})


async def enumerate_account_entries(page: Any) -> list[dict[str, Any]]:
    return await _safe(page.evaluate(ACCOUNT_ENTRY_JS, {"pattern": r"ID\s*[:：]?\s*\d{6,}"}), [])


async def discover_subaccount_entries(page: Any, spec: Any) -> dict[str, Any]:
    """打开子账号选择控件、枚举候选项，最后按 Esc 收起。**本步骤不选择任何账号。**

    不猜选择器：先从"账号 ID 文本"反查元素，再沿祖先链逐级点击（0→3 级），
    哪一级使候选项数量增加，就是选择控件的触发点；整条祖先链一并记录，供登记契约。
    """
    pattern = r"ID\s*[:：]?\s*\d{6,}"
    account_selector = spec.account.selector
    baseline = await enumerate_account_entries(page)
    ancestors = await _safe(
        page.evaluate(ACCOUNT_ANCESTOR_CHAIN_JS, {"pattern": pattern, "levels": 6}), {}
    )
    result: dict[str, Any] = {
        "account_selector": account_selector,
        "account_selector_count": await _safe(page.locator(account_selector).count(), -1),
        "baseline_entries": baseline,
        "ancestor_chain": ancestors,
        "level_attempts": [],
        "menu_opened_by_level": None,
        "entries": [],
        "entries_after_escape": [],
        "notes": [],
    }
    for level in range(4):
        click = await _safe(
            page.evaluate(CLICK_ANCESTOR_JS, {"pattern": pattern, "level": level}), {}
        )
        if not click.get("clicked"):
            result["level_attempts"].append({"level": level, "clicked": False})
            break
        await asyncio.sleep(1.5)
        entries = await enumerate_account_entries(page)
        result["level_attempts"].append(
            {
                "level": level,
                "clicked": True,
                "info": click.get("info"),
                "entries": len(entries),
            }
        )
        if len(entries) > len(baseline):
            result["menu_opened_by_level"] = level
            result["entries"] = entries
            break
        await _safe(page.keyboard.press("Escape"), None)
        await asyncio.sleep(0.8)
    if result["menu_opened_by_level"] is None:
        result["notes"].append("沿祖先链 0—3 级点击均未使候选项增加；祖先链已记录，可据此人工定位")
    await _safe(page.keyboard.press("Escape"), None)
    await asyncio.sleep(0.5)
    result["entries_after_escape"] = await enumerate_account_entries(page)
    return result


async def select_subaccount(page: Any, target_id: str) -> dict[str, Any]:
    """用 Playwright 的真实 locator click 点击唯一目标，不调用 DOM ``click()``。"""
    digits = digits_only(target_id)
    pattern = re.compile(rf"ID\s*[:：]?\s*{re.escape(digits)}(?:\D|$)")
    locator = page.locator("li,div,span,a,button,p").filter(has_text=pattern)
    candidates: list[tuple[int, int, Any, str]] = []
    count = await _safe(locator.count(), 0)
    for index in range(min(int(count or 0), 80)):
        candidate = locator.nth(index)
        if not await _safe(candidate.is_visible(), False):
            continue
        text_value = ((await _safe(candidate.inner_text(), "")) or "").strip()
        if digits not in text_value or len(text_value) > 120:
            continue
        has_matching_descendant = await _safe(
            candidate.evaluate(
                """(el, digits) => Array.from(el.querySelectorAll('li,div,span,a,button,p'))
                  .some((child) => (child.textContent || '').includes(digits))""",
                digits,
            ),
            False,
        )
        if has_matching_descendant:
            continue
        depth = await _safe(
            candidate.evaluate(
                "el => { let n=0; for(let p=el;p;p=p.parentElement)n++; return n; }"
            ),
            0,
        )
        candidates.append((int(depth or 0), len(text_value), candidate, text_value))
    if not candidates:
        return {"clicked": False, "reason": "TARGET_ID_NOT_PRESENT"}
    if len(candidates) != 1:
        return {
            "clicked": False,
            "reason": "TARGET_ID_AMBIGUOUS",
            "candidate_count": len(candidates),
        }
    # Deepest and shortest visible text node is the most specific target.  Normal event bubbling
    # lets the application-owned ancestor handle the click without guessing that ancestor's class.
    candidates.sort(key=lambda item: (-item[0], item[1]))
    _, _, target, text_value = candidates[0]
    box = await _safe(target.bounding_box(), None)
    try:
        await target.click(timeout=5000)
    except Exception as exc:  # noqa: BLE001 - diagnostic result, not a swallowed success
        return {
            "clicked": False,
            "reason": "PLAYWRIGHT_CLICK_FAILED",
            "error_type": type(exc).__name__,
            "candidate_count": len(candidates),
        }
    return {
        "clicked": True,
        "click_method": "playwright_locator",
        "candidate_count": len(candidates),
        "target_text": text_value[:80],
        "bounding_box": box,
    }


CLICK_RECORDER_JS = r"""
() => {
  if (window.__dshClickRecorderInstalled) return true;
  window.__dshClickRecorderInstalled = true;
  window.__dshClicks = [];
  const describe = (el) => {
    if (!el || !el.tagName) return null;
    const path = [];
    let node = el;
    for (let i = 0; i < 5 && node && node.tagName; i += 1) {
      let part = node.tagName.toLowerCase();
      const cls = String(node.className || '')
        .trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
      if (cls) part += '.' + cls;
      path.push(part);
      node = node.parentElement;
    }
    return {
      tag: el.tagName,
      cls: String(el.className || '').slice(0, 140),
      id: el.id || null,
      role: el.getAttribute('role'),
      text: (el.textContent || '').trim().slice(0, 120),
      path: path.join(' < '),
    };
  };
  const record = (kind, event) => {
    const el = event.target;
    const target = describe(el);
    const ancestors = (() => {
      const chain = [];
      let node = el;
      for (let i = 0; i < 5 && node; i += 1) {
        chain.push(describe(node));
        node = node.parentElement;
      }
      return chain;
    })();
    const combined = [target, ...ancestors]
      .filter(Boolean).map((item) => item.text || '').join(' ');
    const accountMatch = combined.match(/ID\s*[:：]?\s*(\d{6,})/);
    const rect = el && el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    const payload = {
      event_id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()),
      kind: kind,
      at: new Date().toISOString(),
      url: location.href,
      target: target,
      ancestors: ancestors,
      account_id: accountMatch ? accountMatch[1] : null,
      bounding_box: rect ? {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
      } : null,
      trusted: !!event.isTrusted,
    };
    window.__dshClicks.push(payload);
    // The Python-side binding survives document destruction.  `pointerdown` is emitted before
    // a click-triggered navigation, which closes the old gap where the in-page array disappeared
    // before the five-second poll could read it.
    if (window.__dshRecordInteraction) void window.__dshRecordInteraction(payload);
  };
  document.addEventListener('pointerdown', (event) => record('pointerdown', event), true);
  document.addEventListener('click', (event) => record('click', event), true);
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const contentType = (response.headers.get('content-type') || '').split(';')[0].trim();
    if (window.__dshRecordNetwork && (contentType === 'application/json'
        || contentType.endsWith('+json'))) {
      try {
        const payload = await response.clone().json();
        const shape = (() => {
          if (Array.isArray(payload)) {
            const first = payload.length ? payload[0] : null;
            return {
              kind: 'array', length: payload.length,
              item_kind: first === null ? null : typeof first,
              item_keys: first && typeof first === 'object' && !Array.isArray(first)
                ? Object.keys(first).sort().slice(0, 80) : [],
            };
          }
          if (payload && typeof payload === 'object') {
            const business = {};
            for (const key of ['code', 'status', 'success', 'errno', 'err_no']) {
              if (Object.prototype.hasOwnProperty.call(payload, key)
                  && ['string', 'number', 'boolean'].includes(typeof payload[key])) {
                business[key] = payload[key];
              }
            }
            return {
              kind: 'object', keys: Object.keys(payload).sort().slice(0, 80),
              business_status: business,
            };
          }
          return {kind: typeof payload};
        })();
        await window.__dshRecordNetwork({
          at: new Date().toISOString(), url: response.url, status: response.status,
          method: String((args[1] && args[1].method) || 'GET').toUpperCase(),
          content_type: contentType, json_shape: shape,
        });
      } catch (_) { /* Playwright response metadata still records the failure. */ }
    }
    return response;
  };
  return true;
}
"""
CLICK_RECORDER_INIT_JS = f"({CLICK_RECORDER_JS})()"


def sanitized_url(url: str) -> dict[str, str]:
    """Return only host/path: query strings and fragments may contain credentials."""
    parsed = urlsplit(url)
    return {"host": parsed.hostname or "", "path": parsed.path or "/"}


def response_shape(payload: Any) -> dict[str, Any]:
    """Bounded JSON structure plus non-sensitive business status scalars."""
    if isinstance(payload, dict):
        keys = sorted(str(key) for key in payload)[:80]
        statuses: dict[str, str | int | float | bool | None] = {}
        for key in ("code", "status", "success", "errno", "err_no"):
            if key not in payload:
                continue
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                statuses[key] = value
        return {"kind": "object", "keys": keys, "business_status": statuses}
    if isinstance(payload, list):
        first = payload[0] if payload else None
        return {
            "kind": "array",
            "length": len(payload),
            "item_kind": type(first).__name__ if first is not None else None,
            "item_keys": sorted(str(key) for key in first)[:80] if isinstance(first, dict) else [],
        }
    return {"kind": type(payload).__name__}


def request_in_diagnostic_scope(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return (
        host == "xingtu.cn"
        or host.endswith(".xingtu.cn")
        or host == "oceanengine.com"
        or host.endswith(".oceanengine.com")
    )


class InteractionCapture:
    """Process-side interaction/network evidence that survives page navigation.

    No headers, bodies, query strings, Cookie values, or storage values are retained.  Identity
    carriers are recorded only through the existing HMAC helper.
    """

    def __init__(
        self,
        context: Any,
        account_selector: str,
        protected_selector: str,
        secret: bytes,
        checkpoint_delays: tuple[float, ...] = (1.0, 3.0, 5.0, 15.0, 30.0),
    ):
        self.context = context
        self.account_selector = account_selector
        self.protected_selector = protected_selector
        self.secret = secret
        self.checkpoint_delays = checkpoint_delays
        self.interactions: list[dict[str, Any]] = []
        self.network: list[dict[str, Any]] = []
        self.navigations: list[dict[str, Any]] = []
        self.checkpoints: list[dict[str, Any]] = []
        self.capture_errors: list[str] = []
        self.pending: set[asyncio.Task[Any]] = set()
        self.last_account_interaction_at: datetime | None = None
        self._seen_events: set[str] = set()

    def _task(self, awaitable: Awaitable[Any]) -> None:
        task = asyncio.create_task(awaitable)
        self.pending.add(task)

        def completed(done: asyncio.Task[Any]) -> None:
            self.pending.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                self.capture_errors.append(type(error).__name__)

        task.add_done_callback(completed)

    async def install(self) -> None:
        async def receive(source: dict[str, Any], payload: dict[str, Any]) -> None:
            event_id = str(payload.get("event_id") or "")
            if event_id and event_id in self._seen_events:
                return
            if event_id:
                self._seen_events.add(event_id)
            event = {
                "event_id": event_id,
                "kind": payload.get("kind"),
                "at": payload.get("at"),
                "url": sanitized_url(str(payload.get("url") or "")),
                "target": payload.get("target"),
                "ancestors": payload.get("ancestors"),
                "account_id": payload.get("account_id"),
                "bounding_box": payload.get("bounding_box"),
                "trusted": bool(payload.get("trusted")),
            }
            self.interactions.append(event)
            if event["account_id"] and event["kind"] == "pointerdown":
                self.last_account_interaction_at = datetime.now(UTC)
                page = source.get("page")
                if page:
                    self._task(self._checkpoint(page, "before-click", 0.0, event_id))
                    for delay in self.checkpoint_delays:
                        self._task(
                            self._checkpoint(page, f"after-click-{int(delay)}s", delay, event_id)
                        )

        async def receive_network(source: dict[str, Any], payload: dict[str, Any]) -> None:
            del source
            if not self._correlated():
                return
            url = str(payload.get("url") or "")
            if not request_in_diagnostic_scope(url):
                return
            self.network.append(
                {
                    "kind": "browser-fetch-response",
                    "at": payload.get("at"),
                    "method": payload.get("method"),
                    "status": payload.get("status"),
                    "content_type": payload.get("content_type"),
                    "url": sanitized_url(url),
                    "json_shape": payload.get("json_shape"),
                }
            )

        await self.context.expose_binding("__dshRecordInteraction", receive)
        await self.context.expose_binding("__dshRecordNetwork", receive_network)
        await self.context.add_init_script(CLICK_RECORDER_INIT_JS)
        for page in self.context.pages:
            await _safe(page.evaluate(CLICK_RECORDER_JS), None)
            self.watch_page(page)
        self.context.on("page", self.watch_page)
        self.context.on("request", self.on_request)
        self.context.on("response", self.on_response)

    def watch_page(self, page: Any) -> None:
        page.on("framenavigated", self.on_frame_navigated)

    def on_frame_navigated(self, frame: Any) -> None:
        if frame != frame.page.main_frame:
            return
        self.navigations.append(
            {"at": datetime.now(UTC).isoformat(), "url": sanitized_url(frame.url)}
        )

    def _correlated(self) -> bool:
        if self.last_account_interaction_at is None:
            return False
        return (datetime.now(UTC) - self.last_account_interaction_at).total_seconds() <= 35

    def on_request(self, request: Any) -> None:
        if not self._correlated() or not request_in_diagnostic_scope(request.url):
            return
        if request.resource_type not in {"document", "xhr", "fetch"}:
            return
        self.network.append(
            {
                "kind": "request",
                "at": datetime.now(UTC).isoformat(),
                "method": request.method,
                "resource_type": request.resource_type,
                "url": sanitized_url(request.url),
            }
        )

    def on_response(self, response: Any) -> None:
        if not self._correlated() or not request_in_diagnostic_scope(response.url):
            return
        if response.request.resource_type not in {"document", "xhr", "fetch"}:
            return
        content_type = (
            str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        )
        item: dict[str, Any] = {
            "kind": "response",
            "at": datetime.now(UTC).isoformat(),
            "status": response.status,
            "resource_type": response.request.resource_type,
            "content_type": content_type,
            "url": sanitized_url(response.url),
        }
        self.network.append(item)
        if content_type == "application/json" or content_type.endswith("+json"):
            self._task(self._enrich_response(item, response))

    async def _enrich_response(self, item: dict[str, Any], response: Any) -> None:
        # Reading ``response.finished()`` for every correlated response creates Playwright
        # on-finished tasks that can outlive a navigation and emit hundreds of unhandled
        # ``Target closed`` warnings. ``response.json()`` already waits for the body and is
        # bounded here, so the extra finished wait adds no evidence.
        payload = await _safe_bounded(response.json(), None, timeout=3.0)
        if payload is not None:
            item["json_shape"] = response_shape(payload)
        else:
            item["json_shape_unavailable"] = True

    async def _checkpoint(self, page: Any, phase: str, delay: float, event_id: str) -> None:
        if delay:
            await asyncio.sleep(delay)
        if page.is_closed():
            self.checkpoints.append(
                {
                    "event_id": event_id,
                    "phase": phase,
                    "at": datetime.now(UTC).isoformat(),
                    "page_closed": True,
                }
            )
            return
        variants = await _safe_bounded(
            account_variants(page, self.account_selector),
            {"count": -1, "texts": [], "visible": False},
        )
        account = next((text for text in variants["texts"] if text), None)
        self.checkpoints.append(
            {
                "event_id": event_id,
                "phase": phase,
                "at": datetime.now(UTC).isoformat(),
                "url": sanitized_url(page.url),
                "account": account,
                "protected_ready_visible": await _safe_bounded(
                    page.locator(self.protected_selector).is_visible(), False, timeout=2.0
                ),
                "signals": await _safe_bounded(
                    signal_hmacs(self.context, page, self.secret), {}, timeout=3.0
                ),
            }
        )

    async def finish(self) -> dict[str, Any]:
        if self.pending:
            timeout = (max(self.checkpoint_delays) if self.checkpoint_delays else 0.0) + 5.0
            done, pending = await asyncio.wait(self.pending, timeout=timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                await _safe(task, None)
        return {
            "interactions": self.interactions,
            "network": self.network,
            "navigations": self.navigations,
            "checkpoints": self.checkpoints,
            "capture_errors": self.capture_errors,
        }


async def record_operator_clicks(
    context: Any,
    page: Any,
    account_selector: str,
    options: argparse.Namespace,
    findings: list[dict[str, Any]],
    capture: InteractionCapture | None = None,
) -> None:
    """记录操作者真实点击（元素/DOM/跳转），用于按实际 DOM 登记契约，而不是猜选择器。

    监听器用 `add_init_script` 安装，**页面跳转后依然存在**（只 evaluate 会被导航清掉，
    2026-10-05 因此记录到 0 次点击）。同时聚合 Context 内所有标签页的点击。
    每次点击后延迟 1.5 秒再快照账号候选，以捕捉弹层展开后的内容；
    停止条件为"最后一次点击后静默 20 秒"或到达硬超时。
    """
    if capture is None:
        await _safe(context.add_init_script(CLICK_RECORDER_INIT_JS), None)
        for candidate in context.pages:
            await _safe(candidate.evaluate(CLICK_RECORDER_JS), None)
    loop = asyncio.get_running_loop()
    hard_deadline = loop.time() + options.record_clicks_seconds
    events: list[dict[str, Any]] = []
    navigations: list[str] = []
    current_url = page.url
    seen_keys: set[str] = set()
    last_click_at: float | None = None
    heartbeat = 0
    print()
    print("=" * 72)
    print("请在这个窗口里按你平时的方式，把子账号切换一遍（点到目标账号即可）。")
    print("我会记录你点的每一个元素和弹层内容；最后一次点击后静默 20 秒即结束。")
    print("=" * 72)
    while True:
        collected: list[tuple[Any, dict[str, Any]]] = []
        if capture is not None:
            collected.extend((page, click) for click in capture.interactions)
        else:
            for candidate in context.pages:
                clicks = await _safe(candidate.evaluate("() => window.__dshClicks || []"), [])
                if isinstance(clicks, list):
                    collected.extend(
                        (candidate, click) for click in clicks if isinstance(click, dict)
                    )
        collected.sort(key=lambda pair: str(pair[1].get("at") or ""))
        for click_page, recorded in collected:
            key = "|".join(
                [
                    str(recorded.get("at")),
                    str((recorded.get("target") or {}).get("path")),
                    str(recorded.get("url")),
                ]
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            event = dict(recorded)
            await asyncio.sleep(1.5)
            event["entries_after_click"] = await enumerate_account_entries(click_page)
            event["account_after_click"] = next(
                (
                    text
                    for text in (await account_variants(click_page, account_selector))["texts"]
                    if text
                ),
                None,
            )
            event["url_after_click"] = sanitized_url(click_page.url)
            events.append(event)
            last_click_at = loop.time()
            target = event.get("target") or {}
            print(
                f"  记录第 {len(events)} 次点击：<{target.get('tag')} "
                f"class={str(target.get('cls'))[:60]!r}> 候选数="
                f"{len(event.get('entries_after_click') or [])}"
            )
        if page.url != current_url:
            navigations.append(sanitized_url(page.url))
            current_url = page.url
        if last_click_at is not None and loop.time() - last_click_at > 20:
            break
        if loop.time() >= hard_deadline:
            print("点击记录达到硬超时，结束记录。")
            break
        heartbeat += 1
        if last_click_at is None and heartbeat % 15 == 0:
            print(f"  …仍在等待点击（剩余约 {int(hard_deadline - loop.time())} 秒）")
        await asyncio.sleep(1.0)
    if not events:
        findings_notes = "未记录到任何点击：请确认是在探针打开的那个 Chrome 窗口内操作"
        print(f"  注意：{findings_notes}")
    else:
        findings_notes = None
    findings.append(
        {
            "kind": "operator-clicks",
            "at": datetime.now(UTC).isoformat(),
            "events": events,
            "navigations": navigations,
            "url_final": sanitized_url(page.url),
            "note": findings_notes,
        }
    )


# 实测（2026-10-05）：账号弹层由 **hover** 打开（JS click 无效）；弹层内含
# `button.change-account-button`（文本"切换"），点击后导航到独立选号页
# `https://www.xingtu.cn/ad/user-center/user/account/auth`。
HOVER_TRIGGERS = (
    "span.el-popover__reference-wrapper",
    "div.navigator-account-info",
    "div[class*='navigator-user']",
    "header.star-navigator [class*='account']",
)
ACCOUNT_SELECTOR_URL = "https://www.xingtu.cn/ad/user-center/user/account/auth"


def _entries_contain(entries: list[dict[str, Any]], digits: str) -> bool:
    return any(
        digits in str(entry.get("digits") or "") or digits in str(entry.get("text") or "")
        for entry in entries
    )


async def select_subaccount_flow(
    page: Any, spec: Any, target_id: str, options: argparse.Namespace
) -> dict[str, Any]:
    """按已实测 DOM 选号：hover 打开账号弹层 → 点目标条目；必要时经"切换"进入独立选号页。

    点击目标条目使用 JS click，**避免真实鼠标移动把 hover 弹层关掉**。
    """
    digits = digits_only(target_id)
    result: dict[str, Any] = {"target": digits, "steps": [], "hovered_by": None, "used_page": None}
    for trigger in HOVER_TRIGGERS:
        locator = page.locator(trigger).first
        if await _safe(locator.count(), 0) == 0:
            result["steps"].append({"hover": trigger, "skipped": "NOT_FOUND"})
            continue
        await _safe(locator.hover(timeout=5000), None)
        await asyncio.sleep(1.5)
        entries = await enumerate_account_entries(page)
        hit = _entries_contain(entries, digits)
        result["steps"].append({"hover": trigger, "entries": len(entries), "targetVisible": hit})
        if hit:
            result["hovered_by"] = trigger
            break
        switch = page.locator("button.change-account-button").first
        if await _safe(switch.count(), 0) > 0:
            result["steps"].append({"clickedSwitchButton": "button.change-account-button"})
            await _safe(switch.click(timeout=5000), None)
            await asyncio.sleep(4)
            await goto(page, ACCOUNT_SELECTOR_URL)
            entries = await enumerate_account_entries(page)
            hit = _entries_contain(entries, digits)
            result["steps"].append(
                {"afterSwitch": page.url, "entries": len(entries), "targetVisible": hit}
            )
            if hit:
                result["hovered_by"] = trigger
                result["used_page"] = page.url
                break
    if result["hovered_by"]:
        result["click"] = await select_subaccount(page, target_id)
        await asyncio.sleep(6)
    else:
        result["click"] = {"clicked": False, "reason": "TARGET_NOT_VISIBLE_AFTER_HOVER"}
    return result


async def hold_open_for_operator(
    context: Any,
    page: Any,
    spec: Any,
    park_url: str,
    options: argparse.Namespace,
    findings: list[dict[str, Any]],
    record: Callable[[Any, str, bool], Awaitable[None]],
    capture: InteractionCapture | None = None,
) -> None:
    """保持窗口打开供人工自由操作：只读轮询当前账号，**不点击、不导航**，并记录操作者点击。

    每秒只读一次账号并打印一行实时状态；每 30 秒落一条观测（避免报告过大）。
    用于人工反复验证"能否切到目标账号、切完是否被回退"。
    """
    if capture is None:
        await _safe(context.add_init_script(CLICK_RECORDER_INIT_JS), None)
        for candidate in context.pages:
            await _safe(candidate.evaluate(CLICK_RECORDER_JS), None)
    if await _safe(page.locator(spec.account.selector).count(), 0) == 0:
        print(f"当前页无账号元素，先引导业务页：{park_url}")
        await goto(page, park_url)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + options.hold_open_seconds
    seen_keys: set[str] = set()
    clicks: list[dict[str, Any]] = []
    index = 0
    print()
    print("=" * 72)
    print(f"窗口会保持打开 {int(options.hold_open_seconds)} 秒，你可以自由反复测试切换账号。")
    print("探针只读地显示当前账号，不会点击、不会跳转。")
    print("你点过的每个元素都会被记录下来，供事后定位。")
    print("=" * 72)
    while loop.time() < deadline:
        variants = await account_variants(page, spec.account.selector)
        account = next((text for text in variants["texts"] if text), None)
        protected = await _safe(page.locator(spec.protected_ready.selector).is_visible(), False)
        sources: list[dict[str, Any]] = []
        if capture is not None:
            sources = capture.interactions
        else:
            for candidate in context.pages:
                raw = await _safe(candidate.evaluate("() => window.__dshClicks || []"), [])
                if isinstance(raw, list):
                    sources.extend(click for click in raw if isinstance(click, dict))
        for click in sources:
            if not isinstance(click, dict):
                continue
            key = "|".join(
                [
                    str(click.get("at")),
                    str((click.get("target") or {}).get("path")),
                    str(click.get("url")),
                ]
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            clicks.append(click)
            target = click.get("target") or {}
            print(
                f"  [点击 {len(clicks)}] <{target.get('tag')} "
                f"class={str(target.get('cls'))[:50]!r}> "
                f"text={str(target.get('text'))[:40]!r}"
            )
        if index % 6 == 0:
            await record(page, f"manual-hold[{index // 6}]", True)
        print(
            f"  账号={account} 受保护页={protected} "
            f"剩余={int(deadline - loop.time())}s 已记录点击={len(clicks)}"
        )
        index += 1
        await asyncio.sleep(5)
    findings.append(
        {
            "kind": "manual-hold",
            "at": datetime.now(UTC).isoformat(),
            "clicks": clicks,
            "polls": index,
            "url_final": sanitized_url(page.url),
        }
    )


async def run_round(
    round_index: int,
    config: Any,
    registry: PlatformRegistry,
    secret: bytes,
    options: argparse.Namespace,
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    spec = registry.session
    assert spec and registry.search
    index_url = derive_index_url(spec)
    runtime = ProbeBrowserRuntime(
        config.model_copy(update={"headless": False}),
        options.private_root,
        omit_project_network_args=options.omit_project_network_args,
        use_system_keychain=options.use_system_keychain,
    )
    observations: list[dict[str, Any]] = []
    sequence = 0

    async with runtime.open() as context:
        page = context.pages[0] if context.pages else await context.new_page()
        adapter = BrowserAdapter(
            context, registry, config.expected_account_id, _noop_guard, live=True
        )
        capture: InteractionCapture | None = None
        if (
            options.record_clicks_seconds > 0
            or options.hold_open_seconds > 0
            or options.select_subaccount
        ):
            capture = InteractionCapture(
                context,
                spec.account.selector,
                spec.protected_ready.selector,
                secret,
            )
            await capture.install()
        try:

            async def record(target_page: Any, phase: str, human: bool = False) -> None:
                nonlocal sequence
                observations.append(
                    await observe(
                        context=context,
                        page=target_page,
                        adapter=adapter,
                        registry=registry,
                        secret=secret,
                        round_index=round_index,
                        sequence=sequence,
                        phase=phase,
                        health_timeout=options.health_timeout,
                        human=human,
                    )
                )
                sequence += 1

            # 冷启动基线必须从受保护业务页开始：有效会话留在登录后的应用，真正
            # 失效才由平台重定向到 SSO。直接打开 SSO 登录入口会污染 A/B，并把仍可
            # 复用的会话表现成“登录页”。index_url 来自已登记的 protected_ready href。
            await goto(page, index_url)
            await record(page, "cold-entry")
            # 只在第 1 轮等待人工：后续轮次必须是"纯冷启动观测"，否则等到人工介入会掩盖漂移。
            if options.await_login_seconds > 0 and round_index == 0:
                await await_manual_login(
                    page,
                    adapter,
                    registry,
                    options,
                    record,
                    # 已登录时应直接落到星图后台首页；market 作为备用页面。
                    park_urls=[index_url, registry.search.entry_url],
                )
            await goto(page, index_url)
            await record(page, "index")

            # 最小验证步骤只在第 1 轮、且只在登录之后执行，避免污染"纯冷启动"观测。
            if round_index == 0 and options.inspect_storage:
                findings.append(
                    {
                        "kind": "storage-structure",
                        "round": round_index,
                        "at": datetime.now(UTC).isoformat(),
                        "url": page.url,
                        "structure": await inspect_storage_structure(page),
                    }
                )
            if round_index == 0 and (options.discover_subaccount or options.select_subaccount):
                discovery = await discover_subaccount_entries(page, spec)
                findings.append(
                    {
                        "kind": "subaccount-discovery",
                        "round": round_index,
                        "at": datetime.now(UTC).isoformat(),
                        "url": page.url,
                        "result": discovery,
                    }
                )
                if options.select_subaccount:
                    selection = await select_subaccount_flow(
                        page, spec, options.select_subaccount, options
                    )
                    findings.append(
                        {
                            "kind": "subaccount-select",
                            "round": round_index,
                            "at": datetime.now(UTC).isoformat(),
                            "target": digits_only(options.select_subaccount),
                            "result": selection,
                        }
                    )
                    await asyncio.sleep(6)
                    # 自动选号是"我方主动操作"，与人工换号同源，故标记为人工窗口，不参与漂移判定。
                    await record(page, "after-select", human=True)
            if round_index == 0 and options.hold_open_seconds > 0:
                await hold_open_for_operator(
                    context,
                    page,
                    spec,
                    registry.search.entry_url,
                    options,
                    findings,
                    record,
                    capture,
                )
            if round_index == 0 and options.record_clicks_seconds > 0:
                if await _safe(page.locator(spec.account.selector).count(), 0) == 0:
                    print("当前页无账号元素（未登录或业务页未加载）；先引导业务页再开始记录。")
                    await goto(page, registry.search.entry_url)
                await record_operator_clicks(
                    context, page, spec.account.selector, options, findings, capture
                )
            await goto(page, registry.search.entry_url)
            await record(page, "market")

            # 同页面反复读取：区分"时间维度的自行改写"与"页面维度的场景差异"。
            for index in range(options.same_page_reads):
                if index:
                    await asyncio.sleep(options.same_page_interval)
                await record(page, f"market-samepage[{index}]")

            # 返回导航：同一进程内换个页面再读，检验是否页面相关。
            await goto(page, index_url)
            await record(page, "index-again")

            # 同一 Context 的第二个标签页：检验多标签页是否读到不同账号。
            second = await context.new_page()
            try:
                await goto(second, registry.search.entry_url)
                await record(second, "tab2-market")
            finally:
                await _safe(second.close(), None)

            # 公开首页作为"未进入业务场景"的对照点。
            await goto(page, "https://www.xingtu.cn/")
            await record(page, "public-root")
        finally:
            if capture is not None:
                findings.append(
                    {
                        "kind": "interaction-capture",
                        "at": datetime.now(UTC).isoformat(),
                        "result": await capture.finish(),
                    }
                )
            findings.append(
                {
                    "kind": "browser-environment",
                    "round": round_index,
                    "at": datetime.now(UTC).isoformat(),
                    "browser_version": runtime.browser_version,
                    "user_agent": runtime.browser_ua,
                    "environment_hash": runtime.environment_hash,
                    "executable": str(config.browser_executable_path)
                    if config.browser_executable_path
                    else None,
                    "channel": config.browser_channel,
                    "profile_directory": str(config.profile_directory.resolve()),
                    "launch_args": runtime.launch_args,
                    "ignored_default_args": (
                        ["--use-mock-keychain"] if options.use_system_keychain else []
                    ),
                    "ab_variant": (
                        "playwright-system-keychain-without-project-network-args"
                        if options.use_system_keychain and options.omit_project_network_args
                        else "playwright-system-keychain"
                        if options.use_system_keychain
                        else (
                            "playwright-without-project-network-args"
                            if options.omit_project_network_args
                            else "playwright-current"
                        )
                    ),
                }
            )
            await adapter.close()

    return observations


def analyse(observations: list[dict[str, Any]]) -> dict[str, Any]:
    # 人工窗口单独统计：操作者在探针打开的窗口里自己登录/换号属于人因，不算平台漂移。
    # 给每条自动观测标记"人工窗口代次"（epoch），跨代次的跳变一律不参与漂移判定，
    # 否则"操作者自己把号换过来"会被误报成 DRIFT_WITHIN_PROCESS。
    human_window = [item for item in observations if item.get("human_interaction_window")]
    automated: list[dict[str, Any]] = []
    epoch = 0
    for item in observations:
        if item.get("human_interaction_window"):
            epoch += 1
            continue
        automated.append({**item, "probe_epoch": epoch})

    readable = [item for item in automated if item.get("account")]
    unreadable = [item for item in automated if not item.get("account")]

    # 只有同一 (轮次, 代次) 内的比较才是纯粹的平台行为。
    per_segment: dict[tuple[int, int], set[str]] = {}
    for item in readable:
        key = (int(item["round"]), int(item["probe_epoch"]))
        per_segment.setdefault(key, set()).add(str(item["account"]))

    same_page_groups: dict[tuple[int, int, str], set[str]] = {}
    for item in readable:
        base_phase = str(item["phase"]).split("[")[0]
        key = (int(item["round"]), int(item["probe_epoch"]), base_phase)
        same_page_groups.setdefault(key, set()).add(str(item["account"]))

    within_page = [
        {"round": key[0], "epoch": key[1], "phase": key[2], "accounts": sorted(value)}
        for key, value in same_page_groups.items()
        if len(value) > 1
    ]
    within_segment = [
        {"round": key[0], "epoch": key[1], "accounts": sorted(value)}
        for key, value in per_segment.items()
        if len(value) > 1
    ]
    # 每轮的"结算状态"取该轮最后一个代次：跨重启比较的是"登录安定之后的账号是否还是它"。
    final_by_round: dict[int, set[str]] = {}
    for (rnd, _epoch), accounts in sorted(per_segment.items()):
        final_by_round[rnd] = accounts
    across_round = sorted({account for value in final_by_round.values() for account in value})

    # 每轮的"可观测性"与"正文身份证据"。第二轮若整轮都读不到账号，绝不能被当成 STABLE ——
    # 那正是"重启后会话不再渲染受保护页"的表现；而正文里露出的 ID 才是漂移的直接证据。
    rounds_seen = sorted({int(item["round"]) for item in automated})
    expected_digits = {
        digits_only(item["account_expected"]) for item in automated if item.get("account_expected")
    }
    per_round_body_ids: dict[int, set[str]] = {}
    observable_rounds: set[int] = set()
    for item in automated:
        rnd = int(item["round"])
        if item.get("account") or item.get("protected_ready_visible"):
            observable_rounds.add(rnd)
        for value in item.get("distinct_account_ids_in_body") or []:
            per_round_body_ids.setdefault(rnd, set()).add(digits_only(str(value)))
    unobservable_rounds = [rnd for rnd in rounds_seen if rnd not in observable_rounds]
    unexpected_body_ids = {
        str(rnd): sorted(values - expected_digits)
        for rnd, values in per_round_body_ids.items()
        if values - expected_digits
    }

    # "稳定"必须同时满足"不漂移"与"等于绑定账号"。读得到账号但从来不等绑定的运行，
    # 是"稳定地错"，绝不能报 STABLE（2026-10-05 验证 B 实际命中过这个缺陷）。
    matches_expected = [bool(item.get("account_matches_expected")) for item in readable]
    never_matched = bool(readable) and not any(matches_expected)

    if not readable:
        verdict = "ACCOUNT_UNREADABLE"
    elif never_matched:
        verdict = "PERSISTENT_ACCOUNT_MISMATCH"
    elif within_page:
        verdict = "DRIFT_WITHIN_PAGE"
    elif within_segment:
        verdict = "DRIFT_WITHIN_PROCESS"
    elif len(final_by_round) > 1 and len({frozenset(v) for v in final_by_round.values()}) > 1:
        verdict = "DRIFT_ACROSS_RESTART"
    elif unobservable_rounds and unexpected_body_ids:
        # 后续轮次读不到账号，但页面正文露出了另一个账号身份：静默漂移。
        verdict = "IDENTITY_CHANGED_WHILE_UNREADABLE"
    elif unobservable_rounds:
        verdict = "SESSION_NOT_OBSERVABLE"
    else:
        verdict = "STABLE"

    # 载体定位：账号变动的同一跳里，哪些 signal 也变了；没变却抖动的计入噪声。
    carrier_votes: Counter[str] = Counter()
    carrier_noise: Counter[str] = Counter()
    stable_signals: Counter[str] = Counter()
    for previous, current in zip(automated, automated[1:], strict=False):
        if (
            previous["round"] != current["round"]
            or previous["probe_epoch"] != current["probe_epoch"]
        ):
            continue
        before, after = previous.get("signals") or {}, current.get("signals") or {}
        delta = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        account_changed = previous.get("account") != current.get("account")
        for key in delta:
            if account_changed:
                carrier_votes[key] += 1
            else:
                carrier_noise[key] += 1
        for key in set(before) & set(after):
            if key not in delta:
                stable_signals[key] += 1

    carriers = [
        {
            "signal": key,
            "changed_with_account": carrier_votes[key],
            "changed_without_account": carrier_noise.get(key, 0),
        }
        for key in sorted(carrier_votes, key=lambda k: (-carrier_votes[k], carrier_noise.get(k, 0)))
    ]
    highlights = [item for item in carriers if item["signal"].split("/")[-1] in HIGHLIGHT_CARRIERS]

    # 跨轮次（重启）比对：账号改变的同一时刻，哪些凭证也变了。跨轮变化天然包含正常会话轮换，
    # 因此这里只陈述"变化集合"，不单独断言因果；但它能把载体从几十个键收敛到一两个。
    round_boundary: list[dict[str, Any]] = []
    for previous_round, current_round in zip(rounds_seen, rounds_seen[1:], strict=False):
        before_items = [item for item in automated if int(item["round"]) == previous_round]
        after_items = [item for item in automated if int(item["round"]) == current_round]
        if not before_items or not after_items:
            continue
        before = before_items[-1].get("signals") or {}
        after = after_items[-1].get("signals") or {}
        changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
        round_boundary.append(
            {
                "from_round": previous_round,
                "to_round": current_round,
                "identity_cookies_changed": [k for k in changed if k.startswith("cookie:")],
                "storage_changed": [k for k in changed if not k.startswith("cookie:")],
                "missing_in_later_round": sorted(set(before) - set(after)),
                "added_in_later_round": sorted(set(after) - set(before)),
                "highlight_changed": [k for k in changed if k.split("/")[-1] in HIGHLIGHT_CARRIERS],
            }
        )

    return {
        "verdict": verdict,
        "observed_accounts": across_round,
        "expected_account_id": automated[0]["account_expected"] if automated else None,
        "account_matches_expected": sorted(
            {bool(item["account_matches_expected"]) for item in readable}
        ),
        "readable_observations": len(readable),
        "unreadable_observations": len(unreadable),
        "unreadable_phases": [item["phase"] for item in unreadable],
        "per_round_accounts": {str(key): sorted(value) for key, value in final_by_round.items()},
        "rounds_observed": rounds_seen,
        "unobservable_rounds": unobservable_rounds,
        "per_round_body_ids": {
            str(key): sorted(value) for key, value in per_round_body_ids.items()
        },
        "unexpected_body_ids": unexpected_body_ids,
        "never_matched_expected": never_matched,
        "drift_within_page": within_page,
        "drift_within_process": within_segment,
        "distinct_ids_in_single_page": sorted(
            {
                tuple(item["distinct_account_ids_in_body"])
                for item in automated
                if len(item.get("distinct_account_ids_in_body") or []) > 1
            }
        ),
        "account_in_iframes": [item for item in automated if item.get("account_in_iframes")],
        "carrier_candidates": carriers,
        "highlight_carriers": highlights,
        "round_boundary_changes": round_boundary,
        "human_window_observations": len(human_window),
        "human_window_accounts": sorted(
            {str(item["account"]) for item in human_window if item.get("account")}
        ),
        "human_window_unreadable": sum(1 for item in human_window if not item.get("account")),
        "limitations": [
            "探针自身会导航；若平台按最近访问解析当前账号，导航顺序可能影响结果",
            "只读观测无法区分平台改写与外部改写，只能把范围收敛到载体层",
            "账号定位器匹配数 != 1 记为 unreadable（对应缺陷 D1），不等于登出",
            "signal 仅是 HMAC，跨运行可比的前提是 HMAC key 不变",
        ],
    }


def run_self_test() -> int:
    """用合成序列验证判定与载体定位；不接触浏览器，也不冒充平台验证。"""
    secret = b"self-test-key-0123456789abcdef"
    failures: list[str] = []

    def observation(
        rnd: int,
        seq: int,
        phase: str,
        account: str | None,
        star: str = "s0",
        tlb: str = "t0",
        human: bool = False,
        body_ids: list[str] | None = None,
        protected: bool = True,
    ) -> dict[str, Any]:
        return {
            "round": rnd,
            "sequence": seq,
            "phase": phase,
            "account": account,
            "human_interaction_window": human,
            "account_expected": "ID: 1",
            "account_matches_expected": account == "ID: 1",
            "distinct_account_ids_in_body": body_ids or [],
            "protected_ready_visible": protected,
            "signals": {
                "cookie:.xingtu.cn/possess_scene_star_id": value_hmac(secret, star),
                "cookie:.xingtu.cn/session_tlb_tag": value_hmac(secret, tlb),
            },
        }

    cases: list[tuple[str, list[dict[str, Any]], str]] = [
        (
            "同一个账号、cookie 稳定",
            [observation(0, i, f"p{i}", "ID: 1") for i in range(4)],
            "STABLE",
        ),
        (
            "同页反复读取就变",
            [
                observation(
                    0, i, "market-samepage[0]" if i > 0 else "market", "ID: 1" if i < 2 else "ID: 2"
                )
                for i in range(3)
            ],
            "DRIFT_WITHIN_PAGE",
        ),
        (
            "同进程内换页面变",
            [observation(0, 0, "cold-entry", "ID: 1"), observation(0, 1, "market", "ID: 2")],
            "DRIFT_WITHIN_PROCESS",
        ),
        (
            "重启后变（run3→run4 同型）",
            [observation(0, 0, "cold-entry", "ID: 1"), observation(1, 0, "cold-entry", "ID: 2")],
            "DRIFT_ACROSS_RESTART",
        ),
        (
            "全新进程账号不可读",
            [
                observation(0, 0, "cold-entry", None, star=""),
                observation(0, 1, "market", None, star=""),
            ],
            "ACCOUNT_UNREADABLE",
        ),
        (
            "未登录→操作者登录并自行换到目标号：人因，不算漂移",
            [
                observation(0, 0, "cold-entry", None, star=""),
                observation(0, 1, "human-login[0]", "ID: 2", star="s1", human=True),
                observation(0, 2, "human-login[1]", "ID: 1", star="s2", human=True),
                observation(0, 3, "index", "ID: 1", star="s2"),
                observation(0, 4, "market", "ID: 1", star="s2"),
            ],
            "STABLE",
        ),
        (
            "操作者换号后才重启，重启前后一致：不算漂移",
            [
                observation(0, 0, "cold-entry", "ID: 9", star="s9"),
                observation(0, 1, "human-login[0]", "ID: 1", star="s1", human=True),
                observation(0, 2, "market", "ID: 1", star="s1"),
                observation(1, 0, "cold-entry", "ID: 1", star="s1"),
            ],
            "STABLE",
        ),
        (
            "重启后整轮读不到账号，正文却露出另一个账号：静默漂移（2026-10-05 真实命中）",
            [
                observation(0, 0, "market", "ID: 1", body_ids=["1"]),
                observation(1, 0, "cold-entry", None, body_ids=["2"], protected=False),
            ],
            "IDENTITY_CHANGED_WHILE_UNREADABLE",
        ),
        (
            "重启后整轮不可观测且正文无账号：会话不可观测（不得报 STABLE）",
            [
                observation(0, 0, "market", "ID: 1", body_ids=["1"]),
                observation(1, 0, "cold-entry", None, body_ids=[], protected=False),
            ],
            "SESSION_NOT_OBSERVABLE",
        ),
        (
            "读得到账号但始终不等于绑定账号：稳定地错，不得报 STABLE（2026-10-05 验证 B 命中）",
            [
                observation(0, 0, "market", "ID: 2", body_ids=["2"]),
                observation(1, 0, "market", "ID: 2", body_ids=["2"]),
            ],
            "PERSISTENT_ACCOUNT_MISMATCH",
        ),
    ]
    for name, sequence, expected in cases:
        actual = analyse(sequence)["verdict"]
        if actual != expected:
            failures.append(f"{name}: 期望 {expected}，实际 {actual}")

    carrier_case = [
        observation(0, 0, "cold-entry", "ID: 1", star="s0", tlb="t0"),
        observation(0, 1, "market", "ID: 2", star="s1", tlb="t0"),
    ]
    top = analyse(carrier_case)["carrier_candidates"]
    if not top or "possess_scene_star_id" not in top[0]["signal"]:
        failures.append(f"载体定位：期望 possess_scene_star_id 排第一，实际 {top[:2]}")
    if any("tlb" in item["signal"] for item in top if item["changed_with_account"]):
        failures.append("载体定位：未变化的 session_tlb_tag 不应被计为共同变化")

    human_check = analyse(
        [
            observation(0, 0, "cold-entry", None, star=""),
            observation(0, 1, "human-login[0]", "ID: 2", star="s1", human=True),
            observation(0, 2, "human-login[1]", "ID: 1", star="s2", human=True),
            observation(0, 3, "market", "ID: 1", star="s2"),
        ]
    )
    if human_check["human_window_accounts"] != ["ID: 1", "ID: 2"]:
        failures.append(f"人工窗口账号记录错误：{human_check['human_window_accounts']}")
    if human_check["human_window_observations"] != 2:
        failures.append(f"人工窗口观测计数错误：{human_check['human_window_observations']}")

    if failures:
        for line in failures:
            print(f"自检失败：{line}", file=sys.stderr)
        return 1
    print(f"自检通过：{len(cases)} 项判定用例 + 2 项载体/人工窗口用例全部符合预期。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="F04/F05 账号漂移只读探针")
    parser.add_argument("--config", type=Path, help="执行单元 JSON")
    parser.add_argument("--rounds", type=int, default=2, help="冷启动轮数（默认 2）")
    parser.add_argument("--gap-seconds", type=float, default=0.0, help="轮间等待秒数")
    parser.add_argument("--same-page-reads", type=int, default=4, help="同页反复读取次数")
    parser.add_argument("--same-page-interval", type=float, default=3.0, help="同页读取间隔秒")
    parser.add_argument("--health-timeout", type=float, default=8.0, help="单次会话判定超时秒")
    parser.add_argument(
        "--await-login-seconds",
        type=float,
        default=0.0,
        help="第 1 轮冷启动后等待人工登录的秒数（>0 时该期间绝不导航）",
    )
    parser.add_argument("--login-poll-seconds", type=float, default=3.0, help="人工登录轮询间隔秒")
    parser.add_argument(
        "--inspect-storage",
        action="store_true",
        help="输出 STAR 相关存储键的**结构**（长度/格式/JSON 键名），不输出任何值",
    )
    parser.add_argument(
        "--discover-subaccount",
        action="store_true",
        help="打开子账号选择控件并枚举候选项后按 Esc 收起（**不选择**任何账号）",
    )
    parser.add_argument(
        "--hold-open-seconds",
        type=float,
        default=0.0,
        help="（>0 时）打开业务页后保持窗口打开 N 秒供人工自由操作（只读轮询，不点击不导航）",
    )
    parser.add_argument(
        "--record-clicks-seconds",
        type=float,
        default=0.0,
        help="（>0 时）记录操作者在窗口内的真实点击与弹层内容，用于按实际 DOM 定位选号入口",
    )
    parser.add_argument(
        "--select-subaccount",
        metavar="ACCOUNT_ID",
        help="发现后自动选中包含该 ID 的子账号，并记录选后校验结果（会改变平台当前账号）",
    )
    parser.add_argument(
        "--omit-project-network-args",
        action="store_true",
        help=(
            "仅用于 local_development A/B：不传 --disable-quic 与 "
            "--force-webrtc-ip-handling-policy；不修改 Playwright 默认参数"
        ),
    )
    parser.add_argument(
        "--use-system-keychain",
        action="store_true",
        help=(
            "仅用于 macOS local_development A/B：只忽略 Playwright 默认的 "
            "--use-mock-keychain，使自然 Chrome profile 继续使用系统钥匙串；不做 stealth"
        ),
    )
    parser.add_argument(
        "--profile-directory-override",
        type=Path,
        help=(
            "仅用于 local_development A/B：改用项目 .runtime 内的隔离测试 profile；"
            "不修改执行单元 JSON"
        ),
    )
    parser.add_argument("--private-root", type=Path, default=ROOT / ".runtime")
    parser.add_argument("--out", type=Path, default=ROOT / ".runtime/drift-probe")
    parser.add_argument("--self-test", action="store_true", help="只跑逻辑自检，不启动浏览器")
    parser.add_argument(
        "--reanalyse",
        type=Path,
        help="只对已存在的报告 JSON 重新分析（不启动浏览器），用于判定逻辑修正后复核历史结果",
    )
    return parser


def run_reanalyse(path: Path) -> int:
    """对历史报告重新分析：判定逻辑修正后无需再跑一次真实观测。"""
    report = json.loads(path.read_text())
    analysis = analyse(report.get("observations") or [])
    print(f"报告：{path}")
    print(f"原判定：{(report.get('analysis') or {}).get('verdict')}")
    print(f"新判定：{analysis['verdict']}")
    print(f"绑定账号：{report.get('expected_account_id')}")
    print(f"各轮导航栏读到：{analysis['per_round_accounts']}")
    print(f"各轮正文出现：{analysis['per_round_body_ids']}")
    if analysis["unexpected_body_ids"]:
        print(f"与绑定不符的正文账号：{analysis['unexpected_body_ids']}")
    if analysis["unobservable_rounds"]:
        print(f"整轮不可观测的轮次：{analysis['unobservable_rounds']}")
    for boundary in analysis["round_boundary_changes"]:
        print(
            f"轮 {boundary['from_round']} → {boundary['to_round']} 跨重启变化："
            f"身份 Cookie {boundary['identity_cookies_changed']}"
        )
        if boundary["storage_changed"]:
            print(f"    storage 变化 {len(boundary['storage_changed'])} 项")
        if boundary["highlight_changed"]:
            print(f"    重点载体同时变化：{boundary['highlight_changed']}")
    if analysis["highlight_carriers"]:
        print("重点载体：")
        for item in analysis["highlight_carriers"]:
            print(
                f"  - {item['signal']}：随账号变化 {item['changed_with_account']} 次，"
                f"未随账号变化 {item['changed_without_account']} 次"
            )
    return VERDICT_EXIT.get(str(analysis["verdict"]), 2)


async def run_live(options: argparse.Namespace) -> int:
    if not options.config:
        print("需要 --config 指向执行单元 JSON", file=sys.stderr)
        return 2
    secret_text = os.environ.get("XINGTU_DIAGNOSTIC_HMAC_KEY")
    if not secret_text or len(secret_text) < 32:
        print("需要 XINGTU_DIAGNOSTIC_HMAC_KEY（至少 32 字符）", file=sys.stderr)
        return 2
    secret = secret_text.encode()
    config = load_unit(options.config)
    if options.omit_project_network_args and not config.is_local_development:
        print("--omit-project-network-args 只允许 local_development 诊断单元", file=sys.stderr)
        return 2
    if options.use_system_keychain and (
        not config.is_local_development or sys.platform != "darwin"
    ):
        print("--use-system-keychain 只允许 macOS local_development 诊断单元", file=sys.stderr)
        return 2
    if options.profile_directory_override:
        if not config.is_local_development:
            print("--profile-directory-override 只允许 local_development", file=sys.stderr)
            return 2
        profile = options.profile_directory_override.resolve()
        private_root = options.private_root.resolve()
        if profile == private_root or not profile.is_relative_to(private_root):
            print("测试 profile 必须位于 --private-root 内部且不能等于根目录", file=sys.stderr)
            return 2
        config = config.model_copy(update={"profile_directory": profile})
    registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
    registry.require_enabled(live=True)
    if not registry.session or not registry.search:
        print("注册表缺少 session/search 契约", file=sys.stderr)
        return 2

    observations: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for round_index in range(options.rounds):
        if round_index and options.gap_seconds:
            print(f"轮间等待 {options.gap_seconds:.0f} 秒（模拟 run3→run4 间隔）…")
            await asyncio.sleep(options.gap_seconds)
        print(f"第 {round_index + 1}/{options.rounds} 轮冷启动观测…")
        observations.extend(
            await run_round(round_index, config, registry, secret, options, findings)
        )

    analysis = analyse(observations)
    observed_at = datetime.now(UTC)
    options.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    report_path = (
        options.out / f"drift-{config.unit_id}-{observed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    descriptor = os.open(report_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(
            {
                "schema_version": "account-drift-probe.v1",
                "observed_at": observed_at.isoformat(),
                "unit_id": config.unit_id,
                "expected_account_id": config.expected_account_id,
                "rounds": options.rounds,
                "gap_seconds": options.gap_seconds,
                "analysis": analysis,
                "probe_findings": findings,
                "observations": observations,
            },
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")

    print()
    print(f"判定：{analysis['verdict']}")
    print(f"绑定账号：{analysis['expected_account_id']}")
    print(f"实测账号：{analysis['observed_accounts']}")
    print(f"可读/不可读：{analysis['readable_observations']}/{analysis['unreadable_observations']}")
    if analysis["unreadable_phases"]:
        print(f"不可读相位：{analysis['unreadable_phases']}")
    if analysis["human_window_observations"]:
        print(
            f"人工窗口观测 {analysis['human_window_observations']} 次："
            f"读到账号 {analysis['human_window_accounts']}，"
            f"不可读 {analysis['human_window_unreadable']} 次（人因，不计入漂移判定）"
        )
    if analysis["highlight_carriers"]:
        print("重点载体：")
        for item in analysis["highlight_carriers"]:
            print(
                f"  - {item['signal']}：随账号变化 {item['changed_with_account']} 次，"
                f"未随账号变化 {item['changed_without_account']} 次"
            )
    for finding in findings:
        kind = finding.get("kind")
        if kind == "storage-structure":
            print("STAR 相关存储键结构（只输出结构，不含值）：")
            for key, meta in sorted((finding.get("structure") or {}).items()):
                print(
                    f"  - {key}: 长度={meta.get('rawLength')} "
                    f"格式={meta.get('formatHint')} json={meta.get('json')}"
                )
        elif kind == "subaccount-discovery":
            result = finding.get("result") or {}
            print(
                f"子账号控件发现：触发层级={result.get('menu_opened_by_level')} "
                f"基线条目={len(result.get('baseline_entries') or [])} "
                f"展开后条目={len(result.get('entries') or [])}"
            )
            chain = (result.get("ancestor_chain") or {}).get("chain") or []
            for node in chain:
                print(
                    f"    祖先链 L{node.get('level')}: <{node.get('tag')} "
                    f"class={node.get('cls')!r} role={node.get('role')}>"
                )
            for attempt in result.get("level_attempts") or []:
                print(f"    点击 L{attempt.get('level')}: {attempt}")
            for entry in result.get("entries") or []:
                print(
                    f"    * <{entry.get('tag')} class={entry.get('cls')!r}> "
                    f"text={entry.get('text')!r} digits={entry.get('digits')}"
                )
            for note in result.get("notes") or []:
                print(f"    说明：{note}")
        elif kind == "operator-clicks":
            events = finding.get("events") or []
            print(f"操作者点击记录 {len(events)} 次：")
            for order, event in enumerate(events, start=1):
                target = event.get("target") or {}
                print(
                    f"  [{order}] <{target.get('tag')} class={target.get('cls')!r} "
                    f"id={target.get('id')}> text={target.get('text')!r}"
                )
                print(f"       path: {target.get('path')}")
                print(
                    f"       点击后候选: "
                    f"{[entry.get('text') for entry in (event.get('entries_after_click') or [])]}"
                )
                print(
                    f"       点击后账号: {event.get('account_after_click')} "
                    f"url={event.get('url_after_click')}"
                )
            if finding.get("navigations"):
                print(f"  发生跳转: {finding['navigations']}")
        elif kind == "subaccount-select":
            print(f"自动选号：目标={finding.get('target')} 结果={finding.get('result')}")
        elif kind == "interaction-capture":
            result = finding.get("result") or {}
            print(
                "跳转安全交互记录："
                f"事件={len(result.get('interactions') or [])} "
                f"请求/响应={len(result.get('network') or [])} "
                f"导航={len(result.get('navigations') or [])} "
                f"选后检查点={len(result.get('checkpoints') or [])}"
            )
        elif kind == "browser-environment":
            print(
                f"浏览器 A/B={finding.get('ab_variant')} "
                f"版本={finding.get('browser_version')} "
                f"环境={finding.get('environment_hash')}"
            )
    print(f"报告：{report_path}")
    return VERDICT_EXIT.get(str(analysis["verdict"]), 2)


def main() -> None:
    options = build_parser().parse_args()
    if options.self_test:
        raise SystemExit(run_self_test())
    if options.reanalyse:
        raise SystemExit(run_reanalyse(options.reanalyse))
    try:
        raise SystemExit(asyncio.run(run_live(options)))
    except CollectorError as exc:
        print(json.dumps({"error_code": exc.code, "reason": exc.reason}), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
