# F04/F05 账号漂移专项检测证据（2026-10-05）

## 目的

把「账号漂移」从推测推进到**可复现判定**：区分「平台自行改写当前账号」与「页面场景差异／人因误判」，并把载体从几十个凭证键收敛到具体键。

## 环境与版本

| 项 | 值 |
|---|---|
| 日期时间 | 2026-10-05 10:59–11:07（+08:00）；报告 `observed_at = 2026-10-05T03:07:22Z` |
| 执行单元 | `unit-local-mac-02`，绑定 `expected_account_id = ID: 1865332309937515` |
| 网络模式 | `local_development`（本地出口，**非生产线路，本次不代表生产验收**） |
| 浏览器 | 真实 Google Chrome（`/Applications/Google Chrome.app`），`headless=false` |
| 测试的代码版本 | 分支 `解决账号飘的问题`，HEAD `2fded60`。本轮改动范围：新增 `scripts/account_drift_probe.py`、修改 `docs/tasks/*`（**均未提交**，故不记录提交号） |
| profile | 先备份 `.runtime/profiles/unit-local-mac-02.bak-20261005T105927`（116M）后删除重建；`expected_account_id` 属不可变绑定，**未改动** |
| 观测设计 | 2 轮冷启动，轮间 180 秒（复现 run 3 → run 4 的约 3 分钟间隔）；每轮含冷启动、逐页面、同页反复读取 4 次、返回导航、第二个标签页、公开首页对照 |

## 实际命令

```bash
# 真实观测（打开 Chrome；第 1 轮等待人工登录并选号，期间探针不导航）
XINGTU_DIAGNOSTIC_HMAC_KEY="$(cat .runtime/drift-probe.hmac-key)" \
.venv/bin/python -u scripts/account_drift_probe.py \
    --config .runtime/units/local-dev-mac-02.json \
    --rounds 2 --gap-seconds 180 --same-page-reads 4 --same-page-interval 3 \
    --await-login-seconds 900

# 离线自检（不启动浏览器）
.venv/bin/python scripts/account_drift_probe.py --self-test

# 对已保存报告重新分析（判定逻辑修正后复核，无需重跑浏览器）
.venv/bin/python scripts/account_drift_probe.py \
    --reanalyse docs/evidence/account-drift-probe-2026-10-05.json
```

实际结束状态：真实观测退出码 **1**（检出漂移）；自检退出码 0（9 项判定用例 + 2 项载体/人工窗口用例通过）；`ruff check` 与 `ruff format --check` 通过。

## 结果：判定 `IDENTITY_CHANGED_WHILE_UNREADABLE`

| 轮次 | 导航栏读到 | 页面正文出现的 ID | 受保护页可见 | 账号定位器匹配数 | 会话判定 |
|---|---|---|---|---|---|
| 0 人工登录并**选定目标子账号**后 | `ID: 1865332309937515` | `1865332309937515` | 是 | 1 | `VALID / PROTECTED_PAGE_AND_ACCOUNT_VERIFIED` |
| 1 同一 profile **Chrome 重启后**、无人工介入 | **读不到** | **`1832740070238347`** | **否** | **0** | `INDETERMINATE / NO_REGISTERED_SESSION_SIGNAL` |

关键事实：

1. 轮 1 的账号定位器匹配数为 **0**、受保护页**从未渲染**；但页面正文里出现的是 **`1832740070238347`** —— 与[两段式验收](SESSION-01-acceptance-2026-09-29.md)记录的 run 4 漂移账号**完全一致**。
2. 轮 0 内部（同一进程）：跨页面、同页反复读取 4 次、返回导航、第二个标签页，账号**始终**为 `ID: 1865332309937515`。据此**排除**「页面场景差异」与「多标签页读到不同账号」两种解释。
3. 公开首页（`https://www.xingtu.cn/`）在轮 0 正文露出目标账号、在轮 1 露出另一账号，与导航栏证据一致。

## 载体收敛（跨重启比对）

跨重启发生变化、且与身份相关的 Cookie **只有 1 个**：

- `cookie:.xingtu.cn/star_sessionid`

以下**逐字节未变**：SSO 登录层（`toutiao_sso_user`、`sso_uid_tt`、`sid_ucp_sso_v1`、`d_ticket`、`ttwid`）、星图业务会话的 `sessionid`、`sessionid_ss`、`sid_tt`、`uid_tt`、`sid_guard`、`has_biz_token`、`is_staff_user`，以及此前被列为头号嫌疑的 **`possess_scene_star_id`** 与 `session_tlb_tag`。

即：**登录身份没变、抖音/巨量侧会话没变，只有星图自己的 `star_sessionid` 变了，而生效账号恰在同一时刻从 A 变成 B。**
本轮数据**否定**了「`possess_scene_star_id` 是漂移载体」这一此前的推测，该假设不再作为下一步依据。

## 结论

1. **漂移已复现**：同一持久 profile、无人工介入、间隔约 3 分钟的一次 Chrome 重启，生效账号从绑定账号 `1865332309937515` 变为 `1832740070238347`。H-A/H-B 由纯推测升级为**已观测现象**。
   本次证据只证明「实际生效账号改变」，**不足以区分**平台侧重新绑定（H-B）与 profile 内多账号声明导致解析不稳定（H-A），二者仍需对照实验。
2. **缺陷 D1 的成因得到解释**：D1 不是「定位器坏了」。漂移发生后，当前子账号无法渲染星图受保护应用壳，于是 `div.navigator-user__userid` 匹配数为 0、受保护页不可见，系统只能得到 `SESSION_INDETERMINATE`。即 **D1 与账号漂移是同一事件的两个视角**，D1 是「错误账号」被归类成「会话不可判定」的**误分类**。
3. **载体收敛到 `star_sessionid`**：跨重启唯一变化的身份 Cookie。
4. **自动化缺少「选定子账号」步骤**（本卡用户现场确认：目标子账号在平台列表中**可见且可选**）：契约 `session` 段没有任何选号动作，代码只「读」不「选」。

## 本轮的自我纠错（必须保留）

首次自动判定输出为 `STABLE`（退出码 0）。复核原始观测后发现这是**判定逻辑缺陷**：第 1 轮没有任何一条可读账号，该轮被跨轮比较**静默忽略**，于是「后续轮次完全读不到账号」被误判为「无漂移」。

已修正为：整轮不可读**不得**判定为 `STABLE`；并新增 `IDENTITY_CHANGED_WHILE_UNREADABLE`（整轮不可读但正文露出不符账号）与 `SESSION_NOT_OBSERVABLE`（整轮不可观测）两个判定，同时补充 9 项判定用例的回归自检。修正后使用 `--reanalyse` 对**同一份已保存报告**离线复算，得到上表的结论——未重跑浏览器、未改动任何观测数据。

## 局限（必须与结论一起引用）

- **单次运行、仅 2 轮**；未做多轮重复，未测漂移的时间窗（是「重启触发」还是「时间触发」）。
- 探针自身会导航；虽然轮 1 完全无人工介入，仍不能完全排除「导航顺序影响平台解析」。
- 跨重启 Cookie 变化天然包含正常会话轮换，`star_sessionid` 是**唯一**变化的身份 Cookie，但**不等于已证明因果**。
- 仅本地开发模式与本地出口，不代表生产线路；账号 ID 按项目既有约定明文记录，Cookie/Storage **值仅为 HMAC**。
- 未验证「重新选定账号后能否稳定保持」，也未验证长期存活。

## 未执行

- 多轮重复与漂移时间窗测量。
- 人工在轮 1 重新选定目标子账号后的稳定性观察。
- 生产线路下的对照，以及与其他客户端并发登录的 H-C 对照。

## 证据文件

- 原始报告（逐条观测 + 凭证 HMAC 指纹）：[account-drift-probe-2026-10-05.json](account-drift-probe-2026-10-05.json)
- 探针脚本：[scripts/account_drift_probe.py](../../scripts/account_drift_probe.py)
- 历史漂移记录与假设登记：[SESSION-01 两段式验收](SESSION-01-acceptance-2026-09-29.md)、[SESSION-01 任务卡](../tasks/SESSION-01.md)
