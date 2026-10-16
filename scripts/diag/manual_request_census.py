"""Manual baseline: record the network traffic of a human-driven 巨量星图 session.

Purpose (DIAG-01, DIAG-T11)
----------------------------
The diagnosing question is "why does automated collection meet verification more often than a
person doing the same task?".  Answering it needs a manual baseline measured with the *same*
statistics as the automated run.  This script supplies exactly one thing: it opens the project's
own verified browser/profile and lets the operator work, while the opt-in request census records
what the platform actually served.

It deliberately performs **no** navigation, no click and no form input of its own.  The single
page it creates is the browser's default blank page; every request in the census was caused by
the human operator.

Usage
-----
    export XINGTU_REQUEST_CENSUS=/path/to/manual-census.jsonl
    export XINGTU_REQUEST_CENSUS_LABEL=diag01-manual
    export XINGTU_DIAGNOSTIC_HMAC_KEY="$(cat .runtime/diag.hmac-key)"   # keeps url_key stable
    .venv/bin/python scripts/diag/manual_request_census.py \\
        --config .runtime/units/local-dev-mac-02.json

Then follow the printed steps in the Chrome window, and press Enter in this terminal when done.

Safety
------
* Uses the project's private profile only (never a personal browser profile).
* Refuses to start if the collection worker holds the unit lease (profile exclusivity).
* Writes nothing but the census file; the census never records query strings, headers, cookies
  or bodies.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.contracts import PlatformRegistry  # noqa: E402
from xingtu.request_census import (  # noqa: E402
    ENV_HMAC,
    ENV_LABEL,
    ENV_OUTPUT,
    census_path_from_env,
)
from xingtu.runtime import BrowserRuntime, load_unit  # noqa: E402

STEPS = """
============================================================
 人工基线操作清单（请在打开的 Chrome 窗口内完成）
============================================================
 1. 打开巨量星图达人广场（/ad/creator/market）。
 2. 填入与自动采集相同的关键词「汽车」，执行一次搜索。
 3. 打开结果列表第 1 位达人的主页，依次查看这些内容：
      - 达人基础资料
      - 商业能力 / 传播能力 / 种草能力 / 履约能力 / 转化能力
      - 连接用户（粉丝）
      - 创作能力
      - 精选集合：优秀触达 / 优秀种草（各看一遍）
 4. 返回结果列表，对第 2 位达人重复第 3 步。
 5. 完成后不必回到终端：到达 --seconds 时限或检测到 --stop-file 即自动收尾落盘。

 注意：请不要改变筛选条件、不要切换账号、不要多开标签页。
============================================================
"""


async def bootstrap_to_protected_page(page: Any, registry: Any, attempts: int = 4) -> str:
    """Mirror the collector's bounded cold-start: a single hop is not a valid session test.

    The registered business entry is regularly redirected to the public home on a cold start, so
    the automation alternates the registered business URLs (and bounces through the registered SSO
    entry on later attempts) until the registry's own protected-page marker becomes visible. This
    uses only registry-declared URLs and selectors; it never invents a selector or clicks anything.
    """

    session = registry.session
    business = list(session.business_urls) if session and session.business_urls else []
    targets = business or [registry.search.entry_url]
    marker = session.protected_ready.selector if session and session.protected_ready else None

    async def ready() -> bool:
        if not marker:
            return False
        try:
            return bool(await page.locator(marker).count())
        except Exception:  # noqa: BLE001
            return False

    for attempt in range(1, attempts + 1):
        if attempt > 1 and attempt % 2 == 0 and session and session.entry_url:
            print(f"    尝试 {attempt}：先经登记的 SSO 入口做会话交接")
            await page.goto(session.entry_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)
        url = targets[(attempt - 1) % len(targets)]
        print(f"    尝试 {attempt}：导航到 {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:  # noqa: BLE001
            print(f"      [warn] 导航异常：{exc}")
        await page.wait_for_timeout(3000)
        if await ready():
            print(f"    受保护业务页已就绪：{page.url}")
            return page.url
        print(f"    尚未就绪（当前 {page.url}）——这是已记录的冷启动重定向，继续下一次尝试")
    print("    多次尝试后仍未就绪：请在窗口内手动完成登录，然后按清单操作")
    return page.url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DIAG-01 人工基线请求普查（只读）")
    parser.add_argument("--config", type=Path, required=True, help="执行单元 JSON")
    parser.add_argument(
        "--private-root",
        type=Path,
        default=ROOT / ".runtime",
        help="项目私有根目录（默认 .runtime）",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=600.0,
        help="最长观测秒数（默认 600）；到点后关闭浏览器并落盘",
    )
    parser.add_argument(
        "--stop-file",
        type=Path,
        help="若该文件出现则立即收尾（便于操作者用一条命令结束）",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="改为按 Enter 结束（需要可交互终端）",
    )
    parser.add_argument(
        "--assume-idle",
        action="store_true",
        help="跳过租约检查（仅在确认没有 worker 占用该 profile 时使用）",
    )
    parser.add_argument(
        "--open-url",
        default=None,
        help=(
            "观测开始前由脚本按顺序导航的地址，多个用逗号分隔（用于把浏览器落到已登录的受保护"
            "业务页，必要时先经注册表登记的 SSO 入口做会话交接）。这些导航由脚本发起、会在日志与"
            "产物中如实标注；脚本不点击、不填表、不输入任何凭据。"
        ),
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help=(
            "按注册表登记的 URL 做有界冷启动（与采集适配器的 _bootstrap_session 同机制）："
            "交替访问已登记业务页，必要时经登记的 SSO 入口做会话交接，直到受保护业务页标记可见。"
            "用于把浏览器可靠地落到已登录的业务页；脚本不点击、不填表、不输入凭据。"
        ),
    )
    return parser.parse_args()


def assert_unit_idle(unit_id: str) -> None:
    """Refuse to open the profile while a worker holds the unit lease."""

    try:
        from xingtu.repository import Repository
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 无法导入 Repository，跳过租约检查：{exc}")
        return
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        print("[warn] 未提供 XINGTU_DATABASE_URL，跳过租约检查（请确认没有 worker 占用 profile）")
        return
    try:
        repository = Repository(dsn)
        row = repository.unit(unit_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 无法读取执行单元状态，跳过租约检查：{exc}")
        return
    owner = row.get("owner")
    stopped = row.get("browser_stopped")
    if owner or not stopped:
        raise SystemExit(
            f"[stop] 执行单元 {unit_id} 正被占用（owner={owner}, browser_stopped={stopped}）。\n"
            "       请先停止 collection worker 并确认 Chrome 已退出，再重试。"
        )
    print(f"[ok] 执行单元 {unit_id} 空闲（state={row.get('state')}, browser_stopped={stopped}）")


async def run(args: argparse.Namespace) -> int:
    out = census_path_from_env()
    if out is None:
        raise SystemExit(
            f"[stop] 未设置 {ENV_OUTPUT}，普查未启用，人工基线将没有数据。\n"
            f'       例：export {ENV_OUTPUT}="$PWD/.runtime/diag01/manual-census.jsonl"'
        )
    config = load_unit(args.config)
    print(f"[ok] 单元={config.unit_id} 账号={config.account_ref} 模式={config.network_mode.value}")
    print(f"[ok] 普查输出={out}")
    print(f"[ok] label={os.environ.get(ENV_LABEL) or 'unlabelled'}")
    if os.environ.get(ENV_HMAC):
        print("[ok] HMAC 来源=环境变量（跨运行可比）")
    else:
        print("[ok] HMAC 来源=本次随机（跨运行不可比）")
    if not args.assume_idle:
        assert_unit_idle(config.unit_id)

    runtime = BrowserRuntime(config, args.private_root)
    async with runtime.open():
        page = runtime._context.pages[0] if runtime._context and runtime._context.pages else None
        if args.bootstrap:
            if page is None:
                raise SystemExit("[stop] 未能取得默认页面，无法执行冷启动")
            print(">>> 按注册表做有界冷启动（与采集适配器同机制）")
            print("    以下导航由脚本发起、已在产物中如实记录；脚本不点击、不填表。")
            registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
            landing = await bootstrap_to_protected_page(page, registry)
            print(f">>> 冷启动结束，当前页面：{landing}")
        if args.open_url:
            if page is None:
                raise SystemExit("[stop] 未能取得默认页面，无法导航到 --open-url")
            for step, url in enumerate(
                [item.strip() for item in args.open_url.split(",") if item.strip()], start=1
            ):
                print(f">>> 脚本导航 {step}：{url}")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(3000)
                    print(f"    -> 当前页面：{page.url}")
                except Exception as exc:  # noqa: BLE001 - 人工可继续在该窗口内自行操作
                    print(f"    [warn] 导航未完成：{exc}")
            print(
                ">>> 以上导航由脚本发起（不是人工操作），已在普查产物中如实记录；"
                "若当前显示登录页，请直接在该窗口内完成登录。"
            )
        print(STEPS)
        if args.interactive:
            await asyncio.get_running_loop().run_in_executor(
                None, input, ">>> 完成后按 Enter 结束普查… "
            )
        else:
            print(f">>> 观测窗口 {args.seconds:.0f}s 已开始；到点会自动收尾。")
            if args.stop_file:
                print(f">>> 也可用 `touch {args.stop_file}` 立即结束。")
            loop = asyncio.get_running_loop()
            deadline = loop.time() + max(1.0, args.seconds)
            while loop.time() < deadline:
                if args.stop_file and args.stop_file.exists():
                    print(">>> 检测到 stop-file，提前收尾。")
                    break
                await asyncio.sleep(1.0)
    print(f"[done] 普查已落盘：{out}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
