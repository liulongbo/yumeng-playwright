# DEPLOY-WIN-01：Windows 星图账号绑定与会话持久化审计

日期：2026-10-31（Asia/Shanghai）  
环境：当前仓库 `快手_1026@c7d12cd`；只读检查本机配置与代码，未连接或操作 Windows 主机。  
结论：**方案可落地，但当前 Windows 星图会话仍是 NO-GO，不能用数据库历史 `VALID` 放行。**

## 1. 用户提供的 Windows 事实

- 星图 Profile 的第 4—8 页只读探测返回 `NO_REGISTERED_SESSION_SIGNAL`；直接访问受保护入口跳转到
  `/?redirect_uri=/ad/creator/market` 并显示“登录”。
- Windows 单元数据库中的 `last_session_status=VALID` 是历史观测；当前进程没有形成 `VALID`。
- 本轮没有 Windows 远程访问授权，也没有重新登录、重启、真实采集、主库写入或生产配置变更。

`NO_REGISTERED_SESSION_SIGNAL` 单独只表示“没有命中已登记的受保护页、登录页、挑战或账号信号”，不能单独
证明 Cookie 缺失；但与实际跳转到登录入口和登录 UI 同时出现时，足以否定“当前冷启动会话可用”。

## 2. 当前绑定方式（代码事实）

### 2.1 运行时绑定源

星图运行时从 Worker 的 `--config <unit.json>` 读取 `UnitConfig`。星图仍兼容顶层旧字段：

| 绑定项 | JSON 字段 | 实际用途 |
|---|---|---|
| 执行单元 | `unit_id` | 队列、Worker、租约及快照文件名 |
| 账号引用 | `account_ref` | 内部资源身份；不得与其他单元重复绑定 |
| 平台账号 | `expected_account_id` | 每次冷启动必须精确核验的星图账号 ID |
| 浏览器 Profile | `profile_directory` | `launch_persistent_context(user_data_dir=...)` 的唯一目录 |
| 平台契约 | `registry_path` | 登录页、受保护页、账号与挑战信号 |
| 浏览器 | `browser_executable_path` | Windows Chrome Stable 的固定可执行文件 |
| 会话快照 | `capture_session_snapshot` | 默认 `true`；显式 storage-state 导出／恢复 |

迁移 020 同时把绑定镜像到 `execution_unit_platform_bindings`，并约束 `(platform, account_ref)`、
`profile_ref` 唯一。数据库用于注册、路由、观测和审计；**当前浏览器实际打开哪个 Profile 仍由 Worker
加载的 JSON 决定**。数据库历史 `last_session_status`／`last_observed_status` 不是新 Chrome 进程的会话证明。

### 2.2 两层会话持久化

星图不是只依赖 Chrome Profile，而是两层同时存在：

1. `profile_directory`：保存普通 Cookie、Local Storage、IndexedDB 及浏览器状态；Windows 由同一 OS 用户的
   Chrome/DPAPI 管理可读性。
2. 私有 storage-state：保存包括 `.xingtu.cn/star_sessionid` 在内的会话级 Cookie，并在下一次 Chrome 的
   **首次导航前**注入。

由正式 CLI／Collection Worker 启动时，`BrowserRuntime` 的 private root 固定为仓库的
`.runtime/profiles`，所以星图快照的权威路径是：

```text
<repo>\.runtime\profiles\storage-state\<unit_id>.json
```

聚星在共享单元模型下使用 `<unit_id>.kuaishou_juxing.json`，不会覆盖星图。旧证据和阶段性工具曾使用
`.runtime/storage-state/`；Windows 正式 Worker 不会读取那个旧位置。不能只检查“某处有快照”，必须检查
**Worker 实际 private root + 当前 unit_id** 对应的文件。

快照只有在当前上下文验证为受保护页面可用且账号与 `expected_account_id` 一致后才允许覆盖；启动时恢复
失败会 fail closed。该 JSON 含活凭据，当前代码依靠私有目录／文件 ACL 隔离，并非应用层加密；不得提交、
上传、打印 Cookie、跨机器随意复制或放进普通备份。

### 2.3 Windows 独占

- 每个平台账号固定一个独立 Profile，同一 Profile 同时只能被一个进程打开。
- Windows 使用 `msvcrt` 项目锁，并结合 Chromium `lockfile` 句柄判断旧浏览器是否仍运行。
- Worker、人工登录维护与冷启动验证必须在同一 Windows 用户下运行；Profile 不得是 symlink/junction，
  不得使用个人 Chrome 的默认目录。
- 仅关闭窗口不等于 Chrome 进程退出；在独占证明前不得启动第二个 Chrome，也不得删除 lockfile。

## 3. 对当前 Windows 故障的判断

从现有证据只能确定“当前星图冷启动没有可用业务会话”，尚不能远程断言唯一根因。优先排查顺序：

1. Worker 实际读取的 `--config` 是否就是星图单元配置，`unit_id` 是否与快照文件名一致；
2. `profile_directory` 是否为星图专属目录，是否在该仓库 `.runtime\profiles\` 内；
3. `<repo>\.runtime\profiles\storage-state\<unit_id>.json` 是否存在、非空，顶层 `unit_id` 是否一致；
4. 登录是否在 Worker 持有的维护窗口完成，并在关闭前形成账号精确匹配与快照导出；
5. Worker／Chrome 是否由另一个 Windows 用户或另一份 checkout 启动；
6. `registry_path` 是否是当前 VERIFIED 星图契约；若页面已登录但信号定位器过期，仍会产生
   `NO_REGISTERED_SESSION_SIGNAL`，此时不能用重新登录掩盖契约问题。

当前本机代码还存在两种历史快照根目录（`.runtime/storage-state` 与
`.runtime/profiles/storage-state`）的证据文件，说明“工具和正式 Worker 使用不同 private root”是现实风险；
Windows 只以正式 Worker 的后者为准。

## 4. Windows 落地方案

### 4.1 固定单一绑定

建议星图使用独立单元 `unit-local-win-01`，聚星继续使用独立单元
`unit-local-win-01-juxing`；两者账号、Profile、快照、队列和 Worker 均不复用。星图配置至少显式包含：

```json
{
  "unit_id": "unit-local-win-01",
  "account_ref": "<xingtu-account-ref>",
  "expected_account_id": "ID: <真实星图账号ID>",
  "line_id": "local-win-01",
  "profile_directory": "C:\\Users\\Administrator\\<repo>\\.runtime\\profiles\\unit-local-win-01",
  "registry_path": "C:\\Users\\Administrator\\<repo>\\contracts\\douyin_xingtu.verified.json",
  "network_mode": "local_development",
  "browser_executable_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "capture_session_snapshot": true,
  "macos_system_keychain": false,
  "headless": false
}
```

若既有数据库绑定与目标账号不同，不得编辑数据库或让程序自动漂移：使用新的 `unit_id`，或在浏览器完全
停止后走已有 `rebind-account` 审计路径。若只是旧 `profile_ref` 指向另一 checkout，而账号不变，最安全的
处理也是创建新 Windows 单元，避免不可变绑定与实际运行路径继续分裂。

### 4.2 在同一受控上下文重新建立会话

1. 停止星图 Collection Worker，确认没有在途租约／接管／验证事件；完整退出星图专属 Chrome。
2. 用同一 Windows 用户、同一 `unit.json`、同一 Worker 启动正式登录维护；不要另开个人 Chrome 登录。
3. 人工完成平台正常短信／设备验证；系统必须在**同一 BrowserContext** 内得到：
   `status=VALID`、`observed_account_id == expected_account_id`、受保护页可用、无登录页／挑战。
4. 在关闭该上下文前确认快照导出成功；只核对元数据，不输出 `storage_state`：

```powershell
$repo = "C:\Users\Administrator\<repo>"
$cfg = Get-Content "$repo\.runtime\units\unit-local-win-01.json" -Raw | ConvertFrom-Json
$snap = "$repo\.runtime\profiles\storage-state\$($cfg.unit_id).json"
$exists = Test-Path $snap
if (-not $exists) { throw "XINGTU_SESSION_SNAPSHOT_MISSING: $snap" }
$meta = Get-Content $snap -Raw | ConvertFrom-Json
[pscustomobject]@{
  path = $snap
  exists = $exists
  bytes = (Get-Item $snap).Length
  schema_version = $meta.schema_version
  unit_id = $meta.unit_id
  captured_at = $meta.captured_at
}
```

5. 正常关闭 Worker 持有的 Chrome，再冷启动同一配置。不得复制 macOS Profile 或把别的 unit 快照改名冒充。

### 4.3 冷启动验收

在业务 Worker 未占用 Profile 时执行脱敏诊断；HMAC Key 只放进当前 PowerShell 环境：

```powershell
$env:XINGTU_DIAGNOSTIC_HMAC_KEY = [Convert]::ToHexString(
  [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
)
python -m xingtu.cli session-diagnostics `
  --config .runtime\units\unit-local-win-01.json `
  --out .runtime\session-diagnostics
```

必须同时满足：

- `session_health.status = VALID`；
- `observed_account_id = expected_account_id`；
- `protected_page_verified = true`，登录页／挑战均未命中；
- `session_snapshot.restored_before_navigation = true`；
- Chrome 正常关闭，Profile 项目锁和 Chromium lockfile 均释放。

随后重启 Collection Worker，并至少再做一次独立冷启动诊断。只有两次冷启动均满足上述条件，才能进行
星图第 4—8 页只读探测；分页探测通过后才讨论更新 v13/3 合同和真实 100 位采集。

## 5. 运维要求

- 服务管理器／Task Scheduler 必须固定工作目录、绝对 `--config` 路径和同一登录用户；有界 Chrome 需要
  交互桌面时，仅在该用户已登录的会话中运行。
- 每次发布前输出非敏感绑定摘要：代码版本、unit_id、配置绝对路径、Profile 绝对路径、registry 版本、
  快照路径／存在性／captured_at、Worker PID/generation；禁止输出 Cookie 内容。
- 备份必须在 Worker 和 Chrome 完全停止后同时备份 Profile 与匹配快照，并用 Windows ACL 限制到服务用户；
  恢复后仍须重新冷启动验证，备份存在不等于服务端会话仍有效。
- 数据库 `READY/VALID` 只用于调度候选，不能跳过每个新 Chrome 进程的结构化 SessionHealth。

## 6. 本轮验证与限制

- 静态回读：`UnitConfig`、`BrowserRuntime`、`BrowserHost`、CLI Worker/diagnostics、迁移 020、Windows F10
  手册及当前本机私有配置的非敏感绑定／快照元数据。
- 未执行 Windows 命令、真实登录、服务重启、平台探测或采集；因此 DEPLOY-WIN-01 保持“进行中”，
  Windows 星图会话验收项保持未勾选。
