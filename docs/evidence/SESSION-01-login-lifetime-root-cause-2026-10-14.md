# 执行单元星图登录状态核验与“登录态快速失效”根因记录（2026-10-14）

> 范围：**真实平台只读核验 + 根因复盘**。对当前唯一注册执行单元 `unit-local-mac-02` 冷启动项目独立 profile，读取 `SessionHealth`；随后按代码、报告与数据库时间线复盘“登录状态为什么很快失效”。
> 结论：**当前登录状态有效**（`SessionHealthStatus.VALID`，账号精确等于绑定账号）；**此前“很快失效”的主因是会话型 Cookie 长期没有落盘快照**，而不是平台会话本身只有几十分钟寿命。
> 未执行：搜索、分页、达人主页采集、任何业务写入、任何任务创建或推进。

## 1. 核验对象与方式

| 项 | 值 | 来源 |
|---|---|---|
| 执行单元 | `unit-local-mac-02`（库中唯一一行） | 开发库 `execution_units` |
| 单元配置 | `.runtime/units/local-dev-mac-02.json` | `load_unit()` |
| 绑定账号 | `ID: 1807978499337419` | 配置 `expected_account_id` |
| 独立 profile | `.runtime/profiles/unit-local-mac-02` | 配置 `profile_directory` |
| 网络模式 | `local_development`（非生产线路） | 配置 `network_mode` |
| 持久快照 | `.runtime/profiles/storage-state/unit-local-mac-02.json`（`0600`） | `BrowserRuntime.session_snapshot_path` |

命令（`2026-10-14T15:49:46+08:00 → 15:49:53+08:00`，exit `0`）：

```bash
set -a; . ./.runtime/m3-app.env; . ./.runtime/development.env; set +a
export PYTHONPATH="$PWD/backend/src" PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers"
export XINGTU_DIAGNOSTIC_HMAC_KEY="$(cat .runtime/diag.hmac-key)"
.venv/bin/xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json
```

> 本次诊断 HMAC 密钥使用新生成的本机密钥 `.runtime/diag.hmac-key`（`0600`，32 字节随机）；历史上用的 `.runtime/drift-probe.hmac-key` 已不在工作区，因此本次报告中的 HMAC 与旧报告不可直接比对（报告 `limitations` 已自述该限制）。

## 2. 核验结论

报告：`.runtime/session-diagnostics/unit-local-mac-02-20261014T074953Z.json`（`0600`，`contains_plaintext_tokens=false`）

```json
"session_health": {
  "status": "VALID",
  "expected_account_id": "ID: 1807978499337419",
  "observed_account_id": "ID: 1807978499337419",
  "protected_page_verified": true,
  "login_page_verified": false,
  "challenge_verified": false,
  "checked_at": "2026-10-14T07:49:52.970751Z",
  "evidence_reason": "PROTECTED_PAGE_AND_ACCOUNT_VERIFIED"
}
```

| 判定项 | 观测 | 含义 |
|---|---|---|
| 会话状态 | `VALID` | 五态中唯一“有效”结论 |
| 账号一致性 | `observed == expected == ID: 1807978499337419` | 精确比对通过，未走人工确认降级 |
| 受保护业务面 | `protected_page_verified=true` | 登录后应用壳已渲染 |
| 登录页 / 安全挑战 | 均为 `false` | 未被重定向登录页，无 `rmc.bytedance.com` 验证码页 |
| 身份来源 | `PROTECTED_PAGE_AND_ACCOUNT_VERIFIED` | **账号 DOM 本次可读**，未使用 `MANUALLY_ATTESTED_UNIQUE_ACCOUNT` |
| 快照复用 | `restored_before_navigation=true` | 本次首个导航前已注入磁盘快照 |
| 浏览器 | Chrome `155.0.8059.40`（Playwright 报告同版本），`headless=false`，`normal_close_confirmed=true` | 真实系统 Chrome、正常关闭 |
| 启动参数 | `--disable-quic --force-webrtc-ip-handling-policy=disable_non_proxied_udp --no-first-run --no-default-browser-check --window-position/size` | 无 `--use-mock-keychain`，`macos_system_keychain=true` 生效 |

**本次是快照路径的首次“无人工确认”正向证据**：此前三次 `VALID` 都带有 `MANUALLY_ATTESTED_UNIQUE_ACCOUNT`（账号 DOM 不可读），本次是账号可读条件下的 `VALID`，且会话来自磁盘快照而非本次输入。

### 2.1 存活时长的新数据点（下界，不是上界）

| 时间（+08） | 事件 | 证据 |
|---|---|---|
| 2026-10-13 16:48 | 第一份有效快照写入（人工确认路径） | `.runtime/profiles/storage-state/unit-local-mac-02.json` `captured_at=2026-10-13T08:48:34Z` |
| 2026-10-13 17:21 | 冷启动复核，`VALID`，快照复用 | `unit-local-mac-02-20261013T092125Z.json` |
| 2026-10-14 10:02 | 真实采集任务 `efb257a6` 结束（`PARTIAL_COMPLETED`） | 库 `root_tasks.updated_at=2026-10-14T02:02:10Z`，单元 `last_session_checked_at` 同刻，`last_session_status=VALID` |
| 2026-10-14 15:49 | 冷启动复核，`VALID`，快照复用，账号可读 | 本轮报告 |

即：**同一份会话至少跨越 3 次冷启动、约 29 小时仍被平台接受**，期间账号未漂移。按 SESSION-01 的记账口径这只增加**下界**数据点；**上界与失效条件仍未测**。

## 3. “登录态为什么很快失效”的机制复盘

### 3.1 直接机制：业务会话是**会话级 Cookie**，落盘与否完全取决于快照

本轮 47 个 Cookie 属性盘点（值只记 HMAC）：

| 类别 | 代表 | 属性 | 影响 |
|---|---|---|---|
| 业务会话 | `.xingtu.cn/star_sessionid` | **`expires=-1`（会话级）** | 只存在于浏览器进程内存，进程结束即不在磁盘 |
| 其他会话级 | `csrf_session_id`、`Hm_lpvt_*`、`HMACCOUNT`、`security_iframe_cookie_detect` | 会话级 | 非认证主载体 |
| SSO/长期 | `d_ticket`、`odin_tt`、`sid_guard`、`sessionid`、`sid_ucp_v1`、`uid_tt` | 59–364 天 | 自动化启动读取 profile 后 SSO 通常仍在 |

因此“登录状态”的存续**不由 Cookie 自带有效期决定**，而由项目的显式机制决定：`BrowserRuntime.export_session_snapshot()` 把整套 Cookie jar + localStorage 写入私有快照，下次启动 `_restore_session_snapshot()` 在**首个导航之前**注入。相关代码：`backend/src/xingtu/runtime.py`（导出 / 恢复 / `framenavigated` 兜底）。

### 3.2 时间线：10-13 16:48 之前**从未产出过快照**，那才是“很快失效”的真相

`.runtime/session-diagnostics/` 全部报告的状态分布：

| 报告 | 状态 | 账号 | 证据原因 | 快照 |
|---|---|---|---|---|
| 2026-10-12T144433Z | `INDETERMINATE` | null | `PROTECTED_PAGE_ACCOUNT_UNREADABLE` | 无 |
| 2026-10-13T075504Z | `INDETERMINATE` | null | `PROTECTED_PAGE_ACCOUNT_UNREADABLE` | 无 |
| 2026-10-13T081546Z | `INDETERMINATE` | null | `PROTECTED_PAGE_ACCOUNT_UNREADABLE` | 无 |
| 2026-10-13T084359Z | `VALID` | 有 | `MANUALLY_ATTESTED_UNIQUE_ACCOUNT` | 无 |
| 2026-10-13T084723Z | `VALID` | 有 | `MANUALLY_ATTESTED_UNIQUE_ACCOUNT` | 无 |
| 2026-10-13T084837Z | `VALID` | 有 | `MANUALLY_ATTESTED_UNIQUE_ACCOUNT` | **首次写入** |
| 2026-10-13T092125Z | `VALID` | 有 | `MANUALLY_ATTESTED_UNIQUE_ACCOUNT` | 复用成功 |
| 2026-10-14T074953Z | `VALID` | 有 | `PROTECTED_PAGE_AND_ACCOUNT_VERIFIED` | 复用成功（本轮） |

* 16:48 之前的所有报告都被判为 `PROTECTED_PAGE_ACCOUNT_UNREADABLE`，快照导出门槛（需账号/DOM 身份证据）不满足 → `storage-state` 文件**不存在**（SESSION-01 卡片 2026-10-13 15:57、16:14 两段记录）。
* 那时“会话是否还有效”与“能不能在下一个进程里用”是两件事：会话在内存里是活的，但**任何一次 Chrome 关闭都把它丢干净**，下一次冷启动只能落在登录页/重定向页。用户主观感受就是“刚登录没多久又失效了”。
* 从首次快照写入（10-13 16:48）起，机制才真正闭环，并已被 ≥29 小时、3 次冷启动验证。

### 3.3 次级放大器（已定位、已缓解或有规避，但仍是风险源）

1. **Playwright 默认 `--use-mock-keychain` 与系统 Keychain 不兼容**（2026-10-05 B2/B3 结论）：会导致 profile 内 Cookie 行在启动读取阶段整体不可读，表现正是“打开就没有登录态”。已通过单元显式 `macos_system_keychain: true`（只忽略该单一默认参数）缓解；**凡是不经项目启动器的冷启动仍会复现**。
2. **多账号/子账号漂移**：重启后平台签发不同 `star_sessionid`，生效账号改变 → `ACCOUNT_MISMATCH`，也会连带让快照身份校验失败。2026-10-06 改绑为“只含单一子账号”的身份后不再复现；**根因（H-A/H-B）仍未区分**。
3. **服务端会话本身没有被证明“短命”**：观测到的失效都可以由“会话级 Cookie 未落盘”“Keychain 读取失败”“账号漂移”解释；尚无证据表明平台对设备/线路设定了固定短寿命。设计不应建立在“平台就是很快踢人”的假设上。

### 3.4 快照机制当前仍存在的可优化缺口（按影响排序）

| 优先级 | 缺口 | 位置 | 现状与后果 |
|---|---|---|---|
| P0 | 快照写入只在“导航事件 + 4 秒防抖 + 页面判定”这条兜底路径上，另有两条显式路径（登录维护 `promote_maintenance_to_collect`、`session-diagnostics`） | `runtime.py`（`_on_frame_navigated` / `_capture_after_navigation`）、`browser_host.py:252` | 直接在达人详情页结束、页面 4 秒内无导航、或关闭时任务来不及完成，都会 `return`／被取消；**合法的有效会话可能整轮不落盘** |
| P0 | 快照写入门槛曾长期要求账号 DOM 证据 | `runtime.py:_session_looks_verified`、`diagnostics.py` | 平台 UI 一改（账号元素不可读）就整链失效 —— 10-13 之前正是如此。人工确认（DEC-016）只是补丁，且 `valid_until=2026-11-12T16:39:32+08:00` 到期后若仍不可读，循环会重现 |
| P1 | 恢复失败静默 | `runtime.py:_restore_session_snapshot`（`except (OSError, ValueError, KeyError, TypeError): return False`） | 失败原因不落任何可观测字段，运维无法区分“快照不在/坏”与“恢复成功但服务端拒绝” |
| P1 | 会话是“热备份”而非长期凭据 | 同上 | 非持久化 Cookie 决定：会话丢失必然落到人工登录，没有自动续期/巡检 |
| P1 | 无阶段性巡检 | — | 只在需要采集时才发现失效，用户被动等在人工登录窗口；SESSION-01 要求的 0/15/30/45/60 分钟至 30 天基线仍未建立 |
| P2 | 跨客户端互踢未排除（H1） | SESSION-01 验收项 | 同账号在别处（日常 Chrome、其他设备）登录是否会使执行单元会话失效，尚未做对照实验 |
| P2 | Chrome 版本漂移 | 单元 `browser_executable_path` | 本次系统 Chrome 已由 154 升到 155，更新发生在“登录仍有效”期间，未见破坏；但主版本跨越时 profile/加密兼容性仍需复核 |
| P2 | 遗留 Playwright stub 进程 | 观测到 3 个 `--no-startup-window` stub（PID 17350/29926/34550）未随诊断退出 | 是否占用其他资源待查；不影响 profile 独占（`flock` + `SingletonLock` 仍有效） |

## 4. 优化建议

1. **会话验证成功即成快照（P0）**：在“新进程进入受保护业务页且账号校验通过”“一次采集 run 正常结束”两个时点各显式 `export_session_snapshot()` 一次，不再只依赖导航防抖兜底；关闭前对最后一次已知有效会话补写快照（已有 `wait_for(pending, timeout=10)`，可再加“先补写、后关闭”的顺序保证）。
2. **身份门槛与快照准入门槛解耦（P0）**：把“会话是否有效”与“能否证明是哪个账号”拆开管理。至少要保证：受保护业务页可用 + 账号不可读时仍能持久化会话（人工确认到期前的替代方案需明确授权）。
3. **恢复可信度可见化（P1）**：把“快照是否存在、`captured_at` 距今多久、注入是否成功、注入失败原因”写入诊断报告、结构化日志与单元状态；采集前若发现快照缺失或过期，先做一次有界续期，而不是等平台拒绝。
4. **定期巡检/续期（P1）**：把 0/15/30/45/60 分钟与 2/6/12/24 小时的观测做成脚本化基线；在长任务开始前做一次轻量会话校验，避免把失效留到人工窗口里才暴露。
5. **人工确认到期的显式决策（P0 运维项）**：`2026-11-12T16:39:32+08:00` 前决定“续签 / 改回可读身份 / 更换绑定身份”，不要让它静默过期。
6. **补做 H1 对照实验（P2）**：确认“同账号在其他客户端登录”是否会踢掉执行单元会话，据此决定是否需要一条明确运维约束。

## 5. 复现与验证命令

```bash
# 只读会话核验（真实 Chrome，冷启动，不开搜索/不采集）
set -a; . ./.runtime/m3-app.env; . ./.runtime/development.env; set +a
export PYTHONPATH="$PWD/backend/src" PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers"
export XINGTU_DIAGNOSTIC_HMAC_KEY="$(cat .runtime/diag.hmac-key)"
.venv/bin/xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json
```

人工登录维护（仅当核验为失效时）：

```bash
.venv/bin/xingtu login --config .runtime/units/local-dev-mac-02.json --wait-seconds 900
```

> 注意：`session-diagnostics` 与 `xingtu login` 都要求独占 profile。执行单元的 Chrome 只要还开着（`SingletonLock` 存在 / `flock` 被占），采集任务会以 `PROFILE_IN_USE` 失败；用完必须**完全退出**（`Command-Q`），不是只关窗口。

## 6. 边界与未完成

* 本次为**只读核验**：不写业务表、不取单元租约，因此库中 `last_session_checked_at` 仍为 `2026-10-14T10:02:10+08` 的采集观测；本次结论以报告文件为准。
* **存活上界仍未测**；“平台会话只有约 45 分钟寿命”这一说法在本轮证据中不成立，但也没有被正式推翻为“可无限期存活”。
* 账号漂移根因（H-A/H-B）、跨客户端互踢（H1）、自动化风控（H2）、启动参数（H3）仍保持 SESSION-01 卡片中的未勾选状态。
* 本记录不构成生产线路（U06/U07/U08）或远程承载验收。
