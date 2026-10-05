# DEC-006：显式本地开发网络模式与生产线路隔离

- 日期：2026-09-27
- 状态：已采纳并实现；真实登录与采集验收未完成

## 待解决问题

技术方案 §1.3 要求先用**本机 IP + Chrome + 真实账号**完成本地验证，之后再落地 J1900/蜂窝线路；同时明确"实现须通过显式开发模式区分本机网络与生产绑定线路，不得伪造 `NetworkProof` 或关闭平台 `VERIFIED`/live 门槛"，且"U07/U08 不因本机验证通过而关闭"。

原实现（`backend/src/xingtu/runtime.py`）把 `proxy_server`、`network_evidence_path`、`network_probe_command` 全部设为必填，`ensure_line` 强制校验 `NetworkProof` 的 `dns_bound`/`disconnect_blocks_direct`/`worker_egress_enforced`。因此本机 IP 无法运行，且唯一"绕过"方式是伪造线路证明——正是规范禁止的做法。

## 选择

1. 领域层新增 `NetworkMode`（`production_line` / `local_development`），`UnitConfig.network_mode` **默认为 `production_line`**，缺省即最严格：既有无 `network_mode` 的配置不会因升级而变成宽松模式。
2. `UnitConfig` 按模式做互斥校验（`model_validator`）：
   - `production_line`：必须提供 `proxy_server`、`network_evidence_path`、`network_probe_command`；
   - `local_development`：**禁止**出现 `proxy_server`、`network_evidence_path`、`network_probe_command`。伪造 `NetworkProof` 无法让本地单元变成生产单元，因为本地模式根本不读取证明文件，而携带证明/代理的本地配置在加载阶段就被拒绝。
3. `ensure_line` 按模式分派：生产路径校验证明与探针（逻辑不变）；本地路径只断言"没有绑定代理"，并返回显式的 `local_network_attestation()` 标记（`egress=local_machine`，**不含** `dns_bound`/`disconnect_blocks_direct`/`worker_egress_enforced`），避免本地证据被误读为线路证明。
4. `BrowserRuntime` 在本地模式不设置 `proxy`；生产模式行为不变。浏览器可执行文件通过 `browser_executable_path` 或 `browser_channel` 显式固定（二者互斥），并在启动后记录 Playwright 报告的真实版本与 UA。
5. 网络模式落到数据库：迁移 `002_unit_network_mode.sql` 增加 `execution_units.network_mode`，`register_unit` 写入并把它纳入**不可变绑定**校验（改模式必须换单元，不允许静默切换）。
6. 新增 `xingtu production-preflight`：生产入口显式要求 `network_mode=production_line` + `require_enabled(live=True)` + `ensure_line` 通过，本地单元一律拒绝（`LOCAL_DEVELOPMENT_UNIT_IS_NOT_A_PRODUCTION_LINE`）。
7. `EvidenceSummary` 增加 `network_mode`，使采集期证据自带网络模式标识；`ExecutionContext` 同样携带该字段。

## 主要替代方案与否决理由

- 允许 `proxy_server=null` 时自动降级直连：会让生产配置错误静默变成直连，违反"线路/隧道断开禁止回落直连"。
- 提供一个"假线路证明"生成命令：直接违反 §1.3 与规范的"不得伪造 NetworkProof"。
- 只加 CLI `--local` 开关而不入库：模式不可审计、不可在运维侧拒绝，也无法阻止后续把本地单元当生产单元使用。

## 兼容性与影响

- 迁移 002 为纯增列（`NOT NULL DEFAULT 'production_line'`），历史配置与历史单元行语义不变；`Repository.migrate` 由"只应用 001"改为按 `schema_migrations` 顺序应用全部待应用迁移。
- `register_unit` 增加带默认值的 `network_mode` 参数，旧调用方行为不变。
- `ExecutionConfig`/`ExecutionContext` 新字段有默认值，无破坏性变更，历史检查点无需改写。
- 生产线路验收（U07/U08）与 §12/§17/§18 要求完全保留；本地证据只证明"浏览器能真实访问平台"，不证明线路隔离。

## 最小验证

- 单测 `backend/tests/unit/test_local_network_mode.py`（11 项）：模式必填项、代理/证明互斥、浏览器绑定互斥、本地模式不产生线路证明字段、`ensure_line` 本地通过且带代理即拒绝、生产无证明即 `LINE_VERIFICATION_UNAVAILABLE`、profile 必须在项目私有根内、配置文件权限、证据网络模式标识、research 模式与主机白名单拒绝。
- 集成测试 `test_network_mode_is_persisted_and_immutable`：迁移 1+2 都已应用、模式入库、改模式被拒。
- 真实执行：`xingtu browser-check` 记录系统 Chrome 154.0.8037.57 与本机 Playwright 1.63.0 的启动兼容性；`xingtu production-preflight` 对本地配置拒绝（见本轮证据）。

## 限制

- 本地阶段尚未取得真实登录与真实采集证据（用户手机不在身边，无法接收平台验证码）；`contracts/douyin_xingtu.verified.json` 仍不存在，平台契约保持未核验。
- 浏览器隔离、DNS、断线禁止直连、旧执行者撤销仍属生产验收（U07/U08），未因本决策关闭。

## 2026-09-27 真实核验后补充

本地阶段随后完成了真实登录与真实采集，DEC-006 的选择得到实测支持，并新增以下必要修正：

1. **会话引导**：平台的应用会话与 SSO 会话不同域，深链不会启动应用。`BrowserAdapter.prepare()` 先访问 `session.entry_url`（SSO 登录入口）并等待 `protected_ready`，再访问 `search.entry_url`；实测在持久会话下可**无人值守**完成（研究轮次 r22）。这符合 F04 §5.2.1「取得租约 → 校验登录身份 → 进入搜索入口」的顺序要求。
2. **账号身份读取改为有界等待**：`check_session` 不再一次性立即读取账号元素，而是有界等待其可见且非空，超时才报 `ACCOUNT_LOGIN_REQUIRED:ACCOUNT_LOCATOR_UNREADABLE`（fail-closed 且可恢复，不再误报模块级失败）。
3. **证据标注网络模式**：`Activities.collect` 现在把 `config.network_mode` 写入 `ExecutionContext`，因此采集期证据能明确标识 `local_development`（此前会保留默认值 `production_line`，属真实缺陷）。
4. **Service Worker 默认策略**：`service_workers` 默认为 `allow`（可用 `block_service_workers=true` 关闭），依据 §13.4「浏览器正常运行平台脚本」。实测表明它**不是**此前登出表象的原因（该表象实为会话域与深链问题），保留该默认值只为贴合规范要求。
5. **Form 控件回读**：`LocatorSpec` 新增 `property`，用于读取输入框的 DOM property `value`——平台的 Element UI 输入框不保证 `value` 属性存在，按属性读取会得到 `None` 并导致条件回读失败。

实测结论：`production_line` 仍要求代理与线路证明，`production-preflight` 仍拒绝本地单元；本地证据用于 F04/F05 的本地功能核验，U07/U08 生产验收保持不变。
