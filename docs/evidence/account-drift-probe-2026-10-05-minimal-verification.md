# 账号漂移最小验证证据（2026-10-05）

本文件回答四个具体问题：① 子账号信息是否被客户端持久保存？② 重启后是否落到默认子账号？③ 自动选号能否做到？④ 选中后能否跨重启保持？

前置证据见 [账号漂移专项检测证据](account-drift-probe-2026-10-05.md)。

## 环境与版本

| 项 | 值 |
|---|---|
| 时间 | 验证 A 2026-10-05 11:27–11:37；验证 B 11:42–11:58（+08:00） |
| 执行单元 | `unit-local-mac-02`，绑定 `expected_account_id = ID: 1865332309937515`（记为 A） |
| 漂移账号 | `ID: 1832740070238347`（记为 B） |
| 网络模式 | `local_development`，**不代表生产线路** |
| 代码版本 | 分支 `解决账号飘的问题`，HEAD `2fded60`；本轮改动为 `scripts/account_drift_probe.py` 的增量（未提交） |
| 观测设计 | 每轮 2 次冷启动、轮间 180 秒、每页反复读 3 次、含第二标签页与公开页对照 |

## 实际命令

```bash
# 验证 A：存储结构 + 选号控件发现 + 保持性
XINGTU_DIAGNOSTIC_HMAC_KEY="$(cat .runtime/drift-probe.hmac-key)" \
.venv/bin/python -u scripts/account_drift_probe.py \
    --config .runtime/units/local-dev-mac-02.json \
    --rounds 2 --gap-seconds 180 --same-page-reads 3 --same-page-interval 3 \
    --await-login-seconds 900 --inspect-storage --discover-subaccount

# 验证 B：自动选号 + 保持性
XINGTU_DIAGNOSTIC_HMAC_KEY="$(cat .runtime/drift-probe.hmac-key)" \
.venv/bin/python -u scripts/account_drift_probe.py \
    --config .runtime/units/local-dev-mac-02.json \
    --rounds 2 --gap-seconds 180 --same-page-reads 3 --same-page-interval 3 \
    --await-login-seconds 600 --select-subaccount 1865332309937515

# 对已保存报告离线复算（判定逻辑修正后）
.venv/bin/python scripts/account_drift_probe.py \
    --reanalyse docs/evidence/account-drift-probe-verifyA-2026-10-05.json
```

退出码：验证 A = 1；验证 B = 0（**其存储判定为缺陷输出，修正后为 `PERSISTENT_ACCOUNT_MISMATCH`，见"自我纠错"**）。`make check` 退出码 0（ruff / format-check / mypy / 105 单测）。

## 验证 A 结果：漂移第二次复现，且这次系统自己认出来了

| 轮次 | 导航栏读到 | 受保护页 | 定位器匹配数 | 会话判定 |
|---|---|---|---|---|
| 0 人工登录后 | `ID: 1865332309937515`（A） | 可见 | 1 | `VALID`（13 条可读） |
| 1 间隔 3 分钟重启 Chrome 后 | **`ID: 1832740070238347`（B）** | **可见** | 1 | **`ACCOUNT_MISMATCH`** |

- 与首次复现（11:07 那份）相比，这次**导航栏正常渲染并读出了 B**，因此系统自身给出 `ACCOUNT_MISMATCH`，不再是 D1 的"不可读"。
- 也就是说：**D1（账号元素不可读）与 `WRONG_ACCOUNT` 是同一次漂移的两种表现**，取决于重启后业务壳是否渲染成功。
- 登录过程中出现 **3 次 `PLATFORM_SECURITY_CHALLENGE`**（由人工完成验证），另有一次 `index` 被重定向到 `/?redirect_uri=/ad/creator/index`、随后 `market` 正常。
- 判定（修正后）：`DRIFT_ACROSS_RESTART`。

## 问题①：子账号信息是否被客户端持久保存？—— 未发现任何持久化记录

`--inspect-storage` 只输出结构（长度/格式/JSON 键名），不含值：

| 键 | 作用域 | 长度 | 结构 |
|---|---|---|---|
| `STAR_NEW_LOCAL_STORAGE_KEY` | localStorage | **2** | json-array，**长度 0（空）** |
| `STAR_GUIDE_LOCAL_STORAGE_KEY` | localStorage | **2** | json-array，**长度 0（空）** |
| `STAR_NEW_SESSION_STORAGE_KEY` | sessionStorage | 309 | array 长度 2，itemKeys `id/name/image/slogan/url/type/queue_type/is_need_localstorage` |
| `STAR_GUIDE_SESSION_STORAGE_KEY` | sessionStorage | 5084 | array 长度 10，itemKeys `id/name/image/slogan/url/is_step_guide/single_config` |

结论与边界：

- **持久层（localStorage）的 STAR 键是空数组**，客户端没有持久保存这一类别名下的子账号信息。
- 有内容的两个键位于 **sessionStorage**，按 Web 语义**不跨浏览器重启保留**。但其字段（`slogan`、`is_step_guide`、`queue_type`）更像**引导/队列**类数据，**不是**子账号描述。
- 因此：**"子账号没有被客户端持久保存"这一半成立；但"它就是漂移载体"未被证明**，本轮没有找到承载子账号的客户端键。
- 结合首次证据（SSO 登录层逐字节未变、唯一变化的身份 Cookie 是 `star_sessionid`），子账号绑定更可能在**服务端**。

## 问题②：重启后是否落到默认子账号？—— 是，两次独立验证都落到 B

验证 B 的冷启动链路被完整记录下来：

1. 冷启动时 profile **有** SSO/巨量登录 Cookie（`sessionid`、`toutiao_sso_user`、`sid_ucp_sso_v1`、`uid_tt`），但**没有 `star_sessionid`**。
2. 此时停在会话入口页（`sso.oceanengine.com/xingtu/login?role=1`），账号元素读不到。
3. 探针主动访问业务页 `https://www.xingtu.cn/ad/creator/market` 引导会话后，**读到账号 = B**，受保护页**可见**。

即：**登录身份还在，但星图业务会话需要"访问业务页"才被签发；一旦被签发，默认落在子账号 B。** 这与你提出的"重启后就是默认子账号"的判断一致。

> 附带的重要发现：**停在 SSO 入口页永远不会建立业务会话**。这解释了历史上"冷启动后账号元素读不到"的一大类现象。

## 问题③：自动选号能否做到？—— 尚未做到，但定位到了控件所在区域

验证 B 的自动选号失败，失败原因是**信息量最大的部分**：

```json
{"clicked": false, "reason": "TARGET_ID_NOT_PRESENT",
 "visibleEntries": ["ID: 1832740070238347"]}
```

探针沿"账号 ID 文本"反查元素，得到祖先链（已记录，可用于登记契约）：

| 层级 | 元素 |
|---|---|
| L0 | `<SPAN class="el-popover__reference-wrapper">`（Element-UI 弹层触发器） |
| L1 | `<SPAN class="">` |
| L2 | `<DIV class="navigator-account-info">` |
| L3 | `<HEADER class="star-navigator">` |

对 L0—L3 逐级点击（JS `click()`）后候选项数量始终为 1，**弹层没有展开出子账号列表**，只显示当前账号 B。

因此可以确定：**这一处是"账号信息弹层"，不是子账号选择列表。** 真正的选号入口尚未定位（可能在其它触发器、独立页面，或仅在登录流程中出现）。按项目规范**不猜测选择器**，故未继续盲试。

## 问题④：选中后能否跨重启保持？—— 不能

验证 A 已给出答案：轮 0 中目标 A 已选定并**在同一进程内全程稳定**（13 条可读、跨页面、跨标签页、同页反复读均为 A），轮 1 间隔约 3 分钟重启后**即回到 B**。

结论：**"一次性选定子账号"无法解决问题**，因为选择不跨 Chrome 重启保持。

## 对方案的含义

1. **自动选号从"可选"升级为"必需"**，且必须**每个新 Chrome 进程都执行一次**（而非只在登录时执行一次）。
2. **"在保存的 Cookie 中增加子账号信息"不可行**：`star_sessionid` 由服务端签发并校验，客户端无法写入；且本轮未找到任何可承载它的客户端槽位。
3. **冷启动必须包含会话引导步骤**（访问业务页），否则业务会话不会被签发。
4. 值得优先调研：平台是否存在能**直接钉住子账号/场景的 URL 参数或接口**（入口已带 `role=1`）。这比驱动界面稳定得多，但**本轮未验证**。
5. 产品备选：B 同样具备星图权限（受保护页可见）。若不坚持 A，可评估**经审计改绑**到 B——但这需要产品决策，且违反"不自动改绑"的现有约束。

## 自我纠错（第 3 次，必须保留）

验证 B 的首次自动判定输出为 `STABLE`（退出码 0）。这是**判定逻辑缺陷**：账号全程为 B、从未等于绑定账号 A，"**稳定地错**"被当成了"稳定"。

已修正：新增 `PERSISTENT_ACCOUNT_MISMATCH` 判定（读得到账号但从不等于绑定账号），并补充回归自检；用 `--reanalyse` 对两份已保存报告离线复算——验证 A → `DRIFT_ACROSS_RESTART`，验证 B → `PERSISTENT_ACCOUNT_MISMATCH`。**未重跑浏览器、未改动任何观测数据。**

至此本探针的判定逻辑已修正 3 次（静默忽略不可读轮次、人工换号误判、稳定地错），每次都由真实数据触发并补齐回归用例，当前自检为 10 项判定 + 2 项载体/人工窗口。

## 局限

- 各 1 次运行；未做多轮重复，未测漂移触发条件是"重启"还是"时间"。
- 自动选号**尚未验证成功**，因此"选号能否修复"与"选号后能否保持"仍是**未回答**的问题。
- 仅本地开发模式与本地出口，不代表生产线路。
- 账号 ID 明文记录（项目既有约定）；Cookie/Storage **值仅为 HMAC**，存储结构检查不输出任何值。

## 未完成与阻塞

- **阻塞**：定位真正的子账号选择入口需要操作者提供人工切换路径（在哪个元素点击、弹层还是独立页面、列表形态），以便按实际 DOM 登记契约，而不是猜测选择器。
- 未完成：自动选号成功后的保持性验证、漂移触发条件与时间窗、平台侧钉住子账号的参数/接口调研。

## 证据文件

- 验证 A 原始报告：[account-drift-probe-verifyA-2026-10-05.json](account-drift-probe-verifyA-2026-10-05.json)
- 验证 B 原始报告（含选号控件祖先链与失败原因）：[account-drift-probe-verifyB-2026-10-05.json](account-drift-probe-verifyB-2026-10-05.json)
- 首次复现证据：[account-drift-probe-2026-10-05.md](account-drift-probe-2026-10-05.md)
- 探针脚本：[scripts/account_drift_probe.py](../../scripts/account_drift_probe.py)
