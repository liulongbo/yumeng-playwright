# 执行单元巨量星图会话实时只读核验（2026-10-12）

> 范围：**真实平台只读核验**。对当前唯一注册执行单元 `unit-local-mac-02` 冷启动项目独立 profile，只访问已登记契约中的受保护入口并读取 `SessionHealth`；**未执行搜索、未采集任何达人、未创建或推进任何任务、未写入业务表**。
> 结论：**有效（`SessionHealthStatus.VALID`）**，账号精确等于单元绑定账号。

## 1. 被核验对象（避免张冠李戴）

| 项 | 值 | 来源 |
|---|---|---|
| 当前执行单元 | `unit-local-mac-02` | 开发库 `execution_units` 仅此一行；`unit-local-mac-01` 未注册 |
| 单元配置 | `.runtime/units/local-dev-mac-02.json` | `load_unit()` |
| 绑定账号 | `ID: 1807978499337419` | 配置 `expected_account_id`，与库中 `expected_account_id` 一致 |
| 独立 profile | `.runtime/profiles/unit-local-mac-02` | 配置 `profile_directory`（`flock` 独占） |
| 网络模式 | `local_development` | 配置 `network_mode`（非生产线路） |
| 运行中的采集 Worker | PID 75094 `xingtu worker --config .runtime/units/local-dev-mac-02.json` | 同一配置文件 |

> 说明：库中只有 `unit-local-mac-02` 一个执行单元，因此"当前执行单元"无歧义。

## 2. 核验前的既有记录（**不是**实时结论）

开发库 `execution_units` 在本次核验前的记录：

```
state=READY, session_version=6, generation=28, owner=NULL, lease_until=NULL,
browser_stopped=true, last_session_status=VALID,
last_session_checked_at=2026-10-11 17:12:41.909083+00:00 (= 2026-10-12 01:12:41+08),
last_session_reason=PROTECTED_PAGE_AND_ACCOUNT_VERIFIED
```

对应最后一次真实采集：根任务 `7a5111cc-49cd-431d-90ca-3120201e809e` 于 2026-10-12 01:12:41+08 `COMPLETED`。

**为什么不能直接引用它作为"此刻有效"**：项目自身契约已明确——

> `backend/src/xingtu/domain.py`：`SessionHealthStatus` — "A persisted execution-unit state is never accepted as proof of a live session. Only a current observation can produce `VALID`."

即库中的 `VALID` 是 **14.4 小时前那一次进程内观测**的结果，不构成本刻的证明。

离线旁证（profile `Default/Cookies` 只读、仅读名称与过期时间，不读值）：16 个相关 Cookie 均在册且未过期，`.xingtu.cn/star_sessionid` 存在（会话级 Cookie，无 `expires`），SSO 类（`toutiao_sso_user`/`sso_uid_tt`/`sid_ucp_sso_v1`/`d_ticket`）与 `sessionid`/`sid_tt`/`sid_guard` 等到 2026-12-05 之后有效。但"Cookie 在"不等于"平台仍接受"，因此仍需一次进程内观测。

## 3. 实际执行的核验命令

```
set -a; . ./.runtime/m3-app.env; set +a
export PYTHONPATH="$PWD/backend/src"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers"
export XINGTU_DIAGNOSTIC_HMAC_KEY="$(cat .runtime/drift-probe.hmac-key)"   # 64 字符，≥32 字节
.venv/bin/xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json
```

- 开始 `2026-10-12T15:36:53+08:00`，结束 `2026-10-12T15:37:01+08:00`，exit `0`。
- 该命令冷启动真实 Chrome 并导航到注册表 `search.entry_url = https://www.xingtu.cn/ad/creator/market`，随后调用 `BrowserAdapter.inspect_session(page)`；不解码、不落盘任何 Cookie/Token 明文（值只写本机 HMAC）。
- 首次尝试因缺少 `PYTHONPATH=backend/src` 报 `ModuleNotFoundError: No module named 'xingtu'`（uv 可编辑安装的 `_editable_impl_*.pth` 为隐藏文件、被 CPython ≥3.13.5 跳过），补上 `Makefile` 中已导出的 `PYTHONPATH` 后正常；此为环境事实记录，非平台结论。

## 4. 核验结果

报告：`.runtime/session-diagnostics/unit-local-mac-02-20261012T073701Z.json`（`0600`，`contains_plaintext_tokens=false`）

```json
"session_health": {
  "status": "VALID",
  "expected_account_id": "ID: 1807978499337419",
  "observed_account_id": "ID: 1807978499337419",
  "protected_page_verified": true,
  "login_page_verified": false,
  "challenge_verified": false,
  "checked_at": "2026-10-12T07:36:58.833087Z",
  "evidence_reason": "PROTECTED_PAGE_AND_ACCOUNT_VERIFIED"
}
```

| 判定项 | 观测 | 含义 |
|---|---|---|
| 会话状态 | `VALID` | 五态中的唯一"有效"结论 |
| 账号一致性 | `observed == expected == ID: 1807978499337419` | 不是"元素可见"而已，而是精确比对通过 |
| 受保护业务面 | `protected_page_verified=true`（`a.navigator-menu-item-link[href="/ad/creator/index"]` 可见） | 登录后应用壳已渲染 |
| 登录页 | `login_page_verified=false` | 未被平台重定向到登录页 |
| 安全挑战 | `challenge_verified=false` | 无 `rmc.bytedance.com/verifycenter/captcha/v2` |
| 浏览器环境 | Chrome `154.0.8037.98`（Playwright 报告同版本），`headless=false`，`normal_close_confirmed=true` | 真实系统 Chrome、正常关闭 |
| 启动参数 | `--disable-quic --force-webrtc-ip-handling-policy=disable_non_proxied_udp --no-first-run --no-default-browser-check --window-position/size` | 无 `--use-mock-keychain`，`macos_system_keychain=true` 生效 |
| 落盘证据 | `Cookies`/`Local State`/`Preferences`/`Session Storage` mtime = `2026-10-12T07:37:01Z`；`localStorage` 出现 `SLARDARstar_fe`、`ARGUS_XSS_V3` 等星图应用键 | 本次确为该 profile 的真实浏览器运行，非缓存复用 |

## 5. 结论与边界

1. **当前执行单元 `unit-local-mac-02` 的巨量星图登录状态为"有效"**，核验时间 `2026-10-12 15:36:58+08:00`；受保护业务面可见且账号精确等于绑定账号 `ID: 1807978499337419`。
2. 同时构成 **SESSION-01 存活观测的新数据点**：上次进程内确证（2026-10-12 01:12:41+08）之后，跨越多小时并跨越新的冷启动，业务会话仍被平台接受，账号未发生子账号漂移（"只含单一子账号"的改绑规避继续成立）。**存活上界仍未测**。
3. **本次核验不写业务库**：`session-diagnostics` 不获取单元租约、不修改 `execution_units`，因此库中 `last_session_checked_at` 仍为 01:12:41+08 的旧观测。本次结论以本节报告文件为准。
4. 边界：`star_sessionid` 是会话级 Cookie，本次核验本身即一次真实平台访问（用户已显式授权只读核验）。该结论**不**代表搜索/主页采集可无限期免登录，也**不**替代生产线路（U07/U08）与远程承载（U06）验收。
5. 未执行：搜索与分页、达人主页采集、任何业务写入、`make check` 全量回归（本次为只读核验，无代码改动）。
