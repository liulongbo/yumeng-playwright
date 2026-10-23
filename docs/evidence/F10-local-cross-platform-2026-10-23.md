# F10 / ExecutionUnit macOS 与 Windows 本地化适配验收（2026-10-23）

## 1. 结论

**总体判定：CONDITIONAL GO。** macOS 本机运行、Worker 在线性、系统 Chrome/Profile、自然
Challenge 检测与 LOCAL_WINDOW 通知已有真实证据；合成接管/失败/恢复 34/34 通过。Windows
实现完成静态与隔离测试，但没有真实 Windows 10/11 主机证据，标记 **NOT TESTED**。本次自然
Challenge 未在 15 分钟内由人工完成，真实恢复同样 **NOT TESTED**，任务按设计部分完成并保留
已持久结果。因此可以进入 Windows 实机/人工恢复验收，不可宣称双平台最终 GO。

## 2. 原实现与跨平台差异

| 范围 | 原实现 | 本轮结果 |
|---|---|---|
| Profile 锁 | `runtime.py` 顶层导入 `fcntl`，仅 POSIX | OS 适配层按需导入；POSIX 保留 `flock`，Windows 使用 `msvcrt` 单字节非阻塞锁 |
| 浏览器停止证明 | POSIX `SingletonLock` PID | POSIX 逻辑保留；Windows 结合项目锁与 Chromium `lockfile` 独占句柄，未知即 fail-closed |
| Chrome | 配置/默认路径偏 macOS | 显式路径优先；macOS/Windows Chrome Stable 路径发现与真实版本报告；显式路径不存在直接失败 |
| Worker 健康 | API 只监测 Intake/Temporal poller，空闲 Collection Worker 退出可能仍显示可用 | 迁移 019 增加独立实例、心跳、停止原因与 `worker_generation`；45 秒窗口内拒绝重复实例 |
| F10 入口 | 无 viewer 时仍偏 Linux/noVNC 文案 | `LOCAL_WINDOW` 与 `REMOTE_VIEWER` 分流；本地提示切换到原 Chrome且不渲染 iframe |
| 启停 | bash、lsof、pgrep、`.venv/bin` | Python supervisor 使用当前解释器、`pathlib`、跨平台 npm 命令，支持 `--check/--status` 与 Ctrl-C |
| Linux | Xvfb/x11vnc/noVNC | 文件和远程 viewer 路径保留；shell/YAML 静态验证通过 |

lease、task generation、owner、browser instance、session version 和 Temporal heartbeat/retry 未被
Worker 监测线程替代或弱化。P1/P2、分页、筛选、字段解析、快照及持久化语义未在本任务中修改。

## 3. 实际修改范围

- `backend/src/xingtu/platform_runtime.py`、`runtime.py`：OS 锁、Windows lockfile 停止证明、私有路径、
  Chrome Stable 发现/版本、跨平台权限处理。
- `migrations/019_execution_unit_worker_liveness.sql`、`repository.py`、`worker.py`：Collection Worker
  注册/心跳/停止/重复拒绝；浏览器关闭错误归类；动作异常后只读复核注册表 Challenge selector。
- `product_models.py`、`product_queries.py`、`product_api.py`：Worker 状态投影；takeover access mode 与
  本机提示；既有 Linux viewer URL 保持兼容。
- `frontend/src/types.ts`、`pages.tsx`、`App.test.tsx`：Worker/浏览器/验证分列，LOCAL_WINDOW 原窗口提示。
- `scripts/m3_up.py`：macOS/Windows 通用前台 supervisor 与 status；`scripts/dev.sh` 保留。
- `scripts/acceptance/run_f10_ui_acceptance.py`：增加本机提示且无 iframe 的验收断言。
- `tests/e2e/test_product_frontend.py`：将既有 E2E 定位器和精选卡片 fixture 对齐当前页面契约。
- [本机运行手册](../F10-local-macos-windows.md)及技术方案/任务卡同步。

工作区原有 QA-01 的 Adapter、筛选注册表、前端资料页等未提交改动均保留，未回滚或覆盖。

## 4. 自动化证据

| 验证 | 结果 |
|---|---|
| Ruff（本轮相关 15 个 Python 文件）/ format / `git diff --check` | PASS |
| mypy | PASS，35 个源码文件 |
| 单元测试 | PASS，315 |
| PostgreSQL 集成 | PASS，95；SKIP 1（MinIO 环境项） |
| Browser Contract | PASS，37 |
| E2E（Temporal + 产品 Chromium） | PASS，9 |
| 前端 TypeScript/Vitest | PASS，84 |
| 前端 production build | PASS |
| F10 Playwright MCP + Chrome 合成验收 | PASS，34/34；console error 0、失败 HTTP 0；环境已清理 |
| Linux shell / Compose 静态校验 | PASS；未启动真实 noVNC 容器 |

全仓 `make lint` 仍被本任务开始前已存在的 `run_cd05/06/07_acceptance.py` 11 个 Ruff UP031
问题阻断；本轮相关文件的 scoped lint/format 全部通过，未擅自修改这些并行 QA 文件。

## 5. macOS 实机

- 系统 Chrome Stable `156.0.8078.47` 与 Playwright `1.63.0`：`browser-check` 启动/开页/关闭
  成功，Profile 为项目独立目录，`browser_stopped=true`。
- 实时 `session-diagnostics`：可见模式、受保护页与绑定账号精确一致、`VALID /
  PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`、正常关闭确认；报告不含明文 token。
- Worker generation 1 正常停止并记录 `CancelledError`，generation 2 持续心跳；第二个 Worker
  以 `DUPLICATE_WORKER_FOR_UNIT` 拒绝。API 返回 `ONLINE / 1 instance`。
- `target=1` 真实小样本发现 20、有效 1 后自然出现 `captcha_container`。首次动作超时暴露了
  `BrowserError` 误归类，已修复为先只读复核注册 Challenge selector；Temporal 下一尝试成功进入
  `WAITING_FOR_VERIFICATION`，通知唯一，原 Chrome 保持、LOCAL_WINDOW ACTIVE、viewer URL 为空。
- 15 分钟内没有人工完成，接管 `TAKEOVER_EXPIRED`；任务按设计
  `PARTIAL_COMPLETED / SECURITY_CHALLENGE_TIMEOUT`，保留 1 位已持久达人。Chrome 安全关闭，租约释放，
  Worker 在线，单元保留 `NEEDS_VERIFICATION`。没有绕过、Cookie 修改或伪造成功。
- 另一个“户外露营/目标 3”任务以
  `PLATFORM_CONDITION_MISMATCH:SELECTED_MISSING:搜索词` 失败；资源正确释放。合入前代码评审确认
  这是 QA-01 新增“提交前条件回读”对 keyword-only 计划的误判（平台只在搜索触发后才渲染关键词
  chip，纯关键词计划在最终提交前没有其他筛选交互可触发搜索），已按 QA-01 范围做最小修复并补
  Browser Contract 用例；当时资源释放正常，真实 keyword-only 回归待执行单元人工验证后补测。

macOS 分项：启动/锁/状态/自然检测/通知/本机原窗口接管 **PASS**；自然 Challenge 人工完成后恢复
**NOT TESTED**；合成恢复 **PASS**。

## 6. Windows 与残余风险

Windows 静态/隔离覆盖：顶层导入可启动、`msvcrt` 锁竞争/释放、共享冲突错误分类、用户目录约束、
Chrome 路径发现、重复 Worker/陈旧心跳/fencing、LOCAL_WINDOW UI。真实 Windows 主机的以下项目均
为 **NOT TESTED**：依赖安装、PostgreSQL/Redis/Temporal、Chrome GUI/Profile 独占、真实 lockfile
句柄、休眠恢复、Ctrl-C 子进程清理、F10 原窗口操作、真实采集、日志/ACL/路径。

剩余门禁：

1. 在 Windows 10/11 执行手册中的完整验收矩阵。
2. 将当前 macOS 单元的自然验证人工完成并确认同一 Context 恢复、`session_version` 仅增加一次。
3. 当前单元为 `NEEDS_VERIFICATION`，再次真实采集前必须由用户完成合法验证并重新形成 SessionHealth。
4. Linux/noVNC 只有静态回归，本轮没有远程实机 PASS。

因此：**代码候选 CONDITIONAL GO；macOS 当前执行单元在人工验证前不可投入下一次真实采集；双平台
正式发布不得升级为 GO。**
