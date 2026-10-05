# UNIT-01 本地真实采集验证（2026-09-27）

> 结论：**F04 真实搜索与 F05 真实主页采集已在本地阶段跑通并落库核对通过（小样本 2 位）**；平台契约由真实交互登记并在 live 门槛下发布。同时明确：这是**本地开发单元**证据，**不构成生产线路/蜂窝验收**；主页只登记了 `basic` 模块、分页只核验首页，相关验收项仍未勾选。
> 命令与数据库原始记录见 [UNIT-01-real-collection-2026-09-27.log](UNIT-01-real-collection-2026-09-27.log)。

## 1. 本轮相对上一阶段的实质变化

| 事项 | 上一阶段（同日早些时候） | 本轮 |
|---|---|---|
| 会话/搜索/主页契约 | 全部未登记（`session/search=null`、`modules=[]`） | 已按真实交互登记并发布为 `xingtu-ad-creator-square-v1`（`contracts/douyin_xingtu.verified.json`） |
| 真实登录 | 因用户手机不在身边无法接收验证码，未完成 | **已完成**：`xingtu login` 校验账号、受保护页面，单元进入 `READY`（session_version=4） |
| F04 真实搜索 | 未执行 | 真实关键词（美妆/内容找人）返回 20 条候选，`pagination.has_more=true` |
| F05 真实采集 | 未执行 | 2 位达人主页 `basic` 模块采集完成并发布快照，`profile_complete=true` |
| 采集落库核对 | 未执行 | 已用 `xingtu status` + PostgreSQL 快照/字段来源核对，并与真实页面身份块对照 |

## 2. 账号与平台限制（真实结论，非代码问题）

- **账号一**（`unit-local-mac-01`）在达人广场搜索时平台返回 `base_resp.status_code=10003`，`status_message="您的客户权益等级过低，暂时无法访问更多数据"`，页面显示"找到 0 个达人"。改用账号二后同一请求 `status_code=0`、返回 20 条。因此该阻塞属**账号权益**而非选择器/接口问题。账号一未登记任何契约。
- 会话入口是 SSO 登录页（`sso.oceanengine.com/xingtu/login?role=1`）。**应用会话与 SSO 会话不是一个域**：新浏览器直接深链到 `/ad/creator/market` 不会启动应用；先访问会话入口完成握手后，深链即可正常加载。这一点已写入适配器引导逻辑（`session.entry_url` → `protected_ready` → `search.entry_url`），并实测可**无人值守**完成（研究轮次 r22）。
- 会话 Cookie 本身是持久的（`sessionid`/`sid_tt`/`uid_tt`/`passport_auth_status` 等均在 profile 中且未过期）。此前"登录失效"的表象来自：①SSO 页与应用的会话域不同；②深链不启动应用；③我早期的固定 sleep 短于握手时间。**不是 Chrome 或 profile 质量问题**。

## 3. 登记的真实契约（要点）

- 会话：入口 `sso.oceanengine.com/xingtu/login?role=1`；受保护就绪 = 后台导航 `a.navigator-menu-item-link[href="/ad/creator/index"]`；账号 = `div.navigator-user__userid`；主页身份 = `div.author-info span.copy-text`。
- 搜索：入口 `/ad/creator/market`；`fill` 关键词输入框 + `click div.el-input-group__append`；回读关键词用 **DOM property `value`**，回读模式用 `span.search-type-radio-item--active`（`内容找人`→`3`）；请求 `POST /gw/api/gsearch/search_for_author_square`，关联 `search_param.keyword`/`search_param.seach_type`/`page_param.page`，成功 `base_resp.status_code=0`；候选 `authors[]`、身份 `star_id`；主页 URL 由**已核验模板** `.../author-homepage/douyin-video/{platform_creator_id}` 生成（搜索响应不含主页 URL）。
- 主页：`basic` 模块 = `GET /gw/api/author/get_author_base_info?o_author_id=$creator_id`，字段 `id/nick_name/avatar_uri/follower/gender/city/province/mcn_name/content_theme_labels`。
- 绑定校验：研究工具 `--bind-check` 证明主页 URL 中的 19 位 ID 来自 `author_get_base_info.id`；真实采集进一步验证 `id_path=star_id` 正确（身份核对未报 CREATOR_INVALID）。

## 4. 真实运行结果（可复现命令）

```bash
xingtu login  --config .runtime/units/local-dev-mac-02.json --wait-seconds 300      # READY, session_version=4
xingtu start  --plan .runtime/plans/local-smoke-beauty.json \
              --config .runtime/units/local-dev-mac-02.json --key <uuid> --actor local-verify
make smoke-local UNIT_CONFIG=.runtime/units/local-dev-mac-02.json ROOT_TASK_ID=<root> TIMEOUT_SECONDS=900
xingtu status <root>
```

实测（root `a48d60c6-5e44-4b56-915d-474304fb4f17`，关键词 `美妆`，目标 2）：

| 指标 | 值 |
|---|---|
| workflow / 任务状态 | `PARTIAL_COMPLETED`（收尾原因 `FEATURED_NOT_ATTEMPTED`，符合本轮不含 F06 的边界） |
| 发现候选 / 本段扫描 | 20 / 20 |
| 有效达人 / 完整档案 | **2 / 2** |
| 未识别候选诊断 | 0 |
| 搜索是否谎报耗尽 | 否（`search_exhausted=false`，达到目标即停止） |

已发布快照（`task_creators ⋈ creator_snapshots`，`profile_complete=true`，`featured_status=NOT_ATTEMPTED`）：

- `first_position=0` → `platform_creator_id=7646720304210771978`，snapshot `5c6472b8-…`
- `first_position=1` → `platform_creator_id=7352866656663633929`，snapshot `c102adf5-…`

字段级核对（`7646720304210771978`/`basic`）：9 个字段全部有状态与来源——`platform_creator_id/nickname/avatar_uri/followers/gender/mcn_name/content_theme_labels` = `COLLECTED`（`source_kind=response`、`path_ref` 为真实 JSON 路径、`observed_at=2026-09-27T09:11:27Z`、`session_version=4`、`source_contract=xingtu-ad-creator-square-v1`），`city/province` = `NO_DATA`（平台返回空串，未伪造成 0 或文本）。

**真实页面 ↔ 持久结果对照**：真实主页 `https://www.xingtu.cn/ad/creator/author-homepage/douyin-video/7646720304210771978` 的页面身份块文本为 `姜乘澜  精选达人 星图ID: 7646720304210771978`，与持久结果的 `platform_creator_id` 与 `nickname=姜乘澜` 一致。

## 5. 失败与修复历史（保留）

| 任务 | 实际失败原因 | 修复 |
|---|---|---|
| `93ab83b7-…` | `MODULE_COLLECTION_FAILED:MISSING_SOURCE`（关键词回读读 input 的 `value` 属性为空；`ready` 定位多匹配） | 新增 `LocatorSpec.property=value` 读 DOM property；`ready` 改为唯一结果区表头 |
| `e8f5c8a8-…` / `5e7f8e1b-…` | `ACCOUNT_LOGIN_REQUIRED:ACCOUNT_LOCATOR_UNREADABLE`（账号定位读取未等待导航渲染） | `read_account` 有界等待账号可见且非空，超时才报不可读 |
| `aeb4cb69-…` | `PLATFORM_CONDITION_MISMATCH:keyword_mode`（`binding_values` 映射早于 `keyword_mode` 绑定生成） | 映射移到全部绑定生成之后 |
| `caed6cf5-…` | `ACCOUNT_LOGIN_REQUIRED: unit needs verification`（登录核验未通过时单元保持 `NEEDS_LOGIN`，采集被正确拒绝） | 先完成登录核验再建任务（流程修正，非代码缺陷） |

这些失败均被保留在任务/证据中，未删除、未降低断言。

## 6. 覆盖缺口（未核验，不得视为通过）

- **多页推进（page 2+）**：研究报告未找到分页控件；契约显式声明 `single_page_only=true` 并记录覆盖缺口，目标数超过首页 20 条时会安全停止，不会重发相同条件或虚报耗尽。**F04 的"分页与终点"验收项仍未勾选。**

> 2026-09-28 AUTO-01 补充：此处是 2026-09-27 的历史证据。真实第 2 页现已通过页面内请求复用验证并限界开放到页 2；页 3+ 与终点仍未验收，F04 状态不变。见[当前账号盘点](AUTO-01-current-account-inventory-2026-09-28.md)。
- **主页模块覆盖**：只登记 `basic`；商业与报价、传播与互动汇总、粉丝画像等尚未登记（`get_author_marketing_info.price_info` 在该账号观察中为空）。**F05 仍为部分核验，实机核验项未勾选。**
- 筛选条件（合作诉求/匹配度/性价比/主题推荐）的填写与回读未核验；只核验了内容关键词模式。
- 访问节奏/限流：`action_interval_seconds=2.0` 为保守值，平台限流阈值未实测。
- 生产线路/DNS/断线隔离/蜂窝/远程维护（U06/U07/U08）、Docker Compose、`make setup`、S3/MinIO：本轮范围外或环境不可用，未执行。

## 7. 脱敏与清理

- 原始研究采集（含页面轮廓与截图）只写入 `.runtime/research/`（`0700`、未纳入版本库），本轮结束后已删除，仅保留本目录的脱敏结论与命令记录。
- 未采集/未写入凭据：证据中不含 Cookie、令牌、请求头或响应正文；账号标识仅以项目内部引用（`xingtu-account-02`）与该账号自身的星图 ID 表示，未记录手机号等信息。
- 达人的联系方式类字段（平台在该账号下可见 `card_info.phone`/`wechat`）**未登记为字段字典**，符合一期"不采集联系方式"的范围约束。
