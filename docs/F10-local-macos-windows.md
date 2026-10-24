# F10 / ExecutionUnit 本机运行手册（macOS 与 Windows）

本手册只描述本地运行方式。Linux/noVNC 部署仍保留；本机单元不需要 Xvfb、x11vnc、
noVNC、systemd、launchd 或 Task Scheduler。本轮不安装开机自启项。

## 共同约束

- 每个 ExecutionUnit 固定一个账号、一个独立 Chrome Profile 和一个 Collection Worker。
- Profile 必须位于项目 `.runtime/profiles/` 私有根目录内，禁止使用个人日常 Chrome Profile。
- Chrome Stable 的显式 `browser_executable_path` 优先；路径不存在时直接失败，不回退到其他浏览器。
- Collection Worker 使用数据库实例心跳和独立 `worker_generation`；45 秒内已有活动实例时，第二个
  Worker 以 `DUPLICATE_WORKER_FOR_UNIT` 拒绝启动。任务 lease/generation/owner 机制保持不变。
- 人工验证时前端显示 `LOCAL_WINDOW`：切换到已经运行的原 Chrome。系统不会启动第二个浏览器、
  强制抢焦点或暴露 CDP。点击“我已完成验证”后仍会校验 Challenge、账号、受保护页面、线路和栅栏。
- `XINGTU_REMOTE_VIEWER_BASE_URL` 只供 Linux/noVNC 使用；配置时仍采用 `REMOTE_VIEWER`。

## macOS

建议配置：

```json
{
  "network_mode": "local_development",
  "browser_executable_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "profile_directory": "/绝对路径/YUMENG/.runtime/profiles/<unit-id>",
  "macos_system_keychain": true,
  "headless": false
}
```

前置检查与前台启动：

```bash
source .venv/bin/activate
python scripts/m3_up.py --check --with-collection --unit-config .runtime/units/<unit>.json
python scripts/m3_up.py --status --with-collection --unit-config .runtime/units/<unit>.json
python scripts/m3_up.py --with-collection --with-frontend --unit-config .runtime/units/<unit>.json
```

最后一条命令保持前台运行，`Ctrl-C` 会依次停止由它启动的子进程。现有 `./dev.sh` 继续作为
macOS 兼容入口，但它依赖 bash、lsof 和 pgrep，不用于 Windows。

## Windows 10/11（PowerShell）

项目与 `.runtime` 应位于当前用户目录（例如
`C:\Users\<user>\Developer\YUMENG`）。配置/Profile 路径不得是符号链接或目录联接；项目依赖
当前用户目录继承 ACL，代码不会用无效的 POSIX chmod 冒充 Windows ACL。

Chrome Stable 常见路径会按顺序发现：`Program Files`、`Program Files (x86)`、
`LocalAppData`。生产式本地配置仍建议显式填写：

```json
{
  "network_mode": "local_development",
  "browser_executable_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "profile_directory": "C:\\Users\\<user>\\Developer\\YUMENG\\.runtime\\profiles\\<unit-id>",
  "macos_system_keychain": false,
  "headless": false
}
```

安装锁定依赖并启动：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
npm --prefix frontend install
python scripts\m3_up.py --check --with-collection --unit-config .runtime\units\<unit>.json
python scripts\m3_up.py --status --with-collection --unit-config .runtime\units\<unit>.json
python scripts\m3_up.py --with-collection --with-frontend --unit-config .runtime\units\<unit>.json
```

Windows Profile 独占使用标准库 `msvcrt` 字节锁。浏览器关闭确认同时检查项目锁和 Chromium
`lockfile` 的独占句柄：共享冲突视为仍运行，无法确认时 fail-closed 并隔离单元；不会删除锁或杀死
无法确认的 Chrome。

## 状态、日志与故障恢复

- 日志：`.runtime/logs/api.log`、`intake-worker.log`、`collection-worker.log`、`frontend.log`。
- API 的执行单元视图将 Worker、浏览器、租约和验证分列。Worker 心跳超过 45 秒显示 `OFFLINE`；
  同一单元若出现多个新鲜实例显示 `DUPLICATE`。
- Worker 异常退出不会由监控线程改写任务；在途 Activity 仍沿用 Temporal 45 秒 heartbeat
  timeout/retry。浏览器关闭或 transport 断开会安全释放 lease，停止状态无法确认则隔离单元。
- Collection Worker 启动时，在注册自己的 Worker generation 后，会对 `QUARANTINED` 单元做一次
  本地停止证明与审计回收：仅在没有活跃租约、`OPEN/ACKNOWLEDGED` 验证事件或
  `REQUESTED/ACTIVE/VERIFYING` 接管，且项目 Profile 锁 + Chromium SingletonLock/lockfile 证明
  浏览器已停止时，调用既有 `recover_stopped_unit()`（actor 为 `collection-worker:<instance>`）。
  证明失败或存在活跃 claim 时保持隔离，Worker 继续服务队列；不得删除锁、杀进程或改 generation。
  仍可手工执行 `xingtu recover-unit --config … --actor …` 作为兜底。
- 用户点击完成但 Challenge 仍在、账号不符、受保护页不可用或 Worker 已失联时拒绝恢复，并显示
  可行动原因。不要修改 Cookie、删除 Singleton/lockfile，或启动第二个 Chrome 处理同一 Profile。
- 休眠恢复后先运行 `--status`。若 Worker 为 `OFFLINE`，确认旧进程已退出并等待心跳超时，再启动；
  不要通过修改数据库时间或 generation 强制接管。

## 验收边界

macOS 可在本机执行 `xingtu browser-check` 和 `xingtu session-diagnostics`；后者会真实访问受保护页，
需要至少 32 字节的 `XINGTU_DIAGNOSTIC_HMAC_KEY`。Windows 必须在真实 Windows 10/11 主机完成
Chrome/Profile、进程、路径、F10 与恢复验收；静态测试或 monkeypatch 结果不能记为实机 PASS。
