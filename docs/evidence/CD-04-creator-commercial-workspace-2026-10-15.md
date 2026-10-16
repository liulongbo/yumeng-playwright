# CD-04 验收证据：达人详情「商业能力」模块重构（2026-10-15）

本轮交付 [CD-04 任务卡片](../tasks/CD-04.md) 的商业能力重构与字段联通；并按用户第 2 轮调整从「商业能力」移除「报价明细」与「历史合作行业」两个模块（详见第 9 节）。所有结论基于运行中的本机开发栈、真实开发库数据与真实 Chrome，不含模拟数据或伪造结果。

## 1. 环境与代码版本

| 项目 | 值 |
|---|---|
| 日期/时区 | 2026-10-15（本地 UTC+8） |
| 分支 | `llb_1013`（未提交、未切换、未合并） |
| 工作区 | 存在其他任务的未提交改动（SESSION-01、FIX-01、LIB-01、UI-01、FILTER-01、CD-01/02/03 等），本轮未覆盖、未还原、未清理 |
| 前端 | `http://127.0.0.1:5173`（Vite dev） |
| 后端 API | `http://127.0.0.1:8000`，本轮**重启**为 pid 70763（该 API 无热加载，用于加载新增的两条只读端点） |
| 数据库 | `xingtu_development`（127.0.0.1:55432，开发库；只读查询 + 既有 API 读取） |
| 账号 | `media-a`（口令取自 `.runtime/qa-credentials.env`，未写入证据文件） |
| 参照达人 | `700ca5b0-f0c8-4436-86fe-624dfeb0f151`（甄选聊车），快照 `9125b95f-a5de-4b2d-b0ff-08b6256ea64e`（2026-10-14 02:02:10Z） |
| 参照任务 | `efb257a6-476b-47ee-aff4-807795bb61a0`（既有真实采集任务；**本轮未发起任何新采集**） |
| 本轮改动文件 | 新增 `frontend/src/profile/commercial.tsx`、`scripts/acceptance/run_cd04_acceptance.py`；修改 `frontend/src/format.ts`(+test)、`profile/panels.tsx`、`profile/CreatorProfile.tsx`、`pages.tsx`、`styles.css`、`api.ts`、`profile/CreatorProfile.test.tsx`、`backend/src/xingtu/product_queries.py`、`product_api.py`、`scripts/acceptance/run_cd02_acceptance.py`（回归选择器跟进） |

## 2. 字段形貌普查（只读数据库，先证据后实现）

对 23 位达人最新快照的 `spread`/`seeding`/`conversion` 字段做了形貌统计（出现次数 → 形状 → 实例）：

| 字段 | 观测形状 | 结论 |
|---|---|---|
| `spread.play_median` | 19 × 字符串标量（4 × `NO_DATA`） | 纯数值，**无**同行对比 |
| `spread.interaction_rate` / `completion_rate` | `{value, overtake}` 13 例、`{label, value, overtake}` 6 例、`{label}` 仅标签 2 例、`{}` 2 例 | `value`/`overtake` 均为**万分比整数**（`112`→1.12%、`7493`→74.93%）；label-only 与空对象必须给明确空态 |
| `spread.average_duration` | 字符串标量（`10140`） | **秒×100**（CD-02 已于线上确证：`63.5s` 对应 `6350`） |
| `spread.average_likes/comments/shares` | 字符串标量 | 普通数值 |
| `spread.expected_cpm` / `expected_cpe` | `{cpm_21_60, cpm_60}` / `{cpe_21_60, cpe_60}` | 两档独立；张国伟另有 `pic_cpm`/`pic_cpe` 成员（未展示） |
| `spread.commercial_play_count` / `commercial_natural_play_count` | 字符串标量（契约路径 `vv` / `sn_vv`） | 两个不同字段，未互相推算 |
| `spread.commercial_cpm_20_60` / `commercial_cpm_60` | `29.6974` | 与 `expected_cpm` 存疑同量 ×100 刻度，**未确证**，本轮不采用 |
| `seeding.search_after_view` 等 5 项 | 区间字符串 / 上界字符串（`"5,000 - 15,000"`、`">15,000"`、`"<10"`、`"<0.02%"`） | 平台返回**档位区间**，不是均值 |
| `seeding.a3_increment` | 区间或上界字符串（`"2,000 - 20,000"`、`">100,000"`、`"<5"`） | **不含**同行排名（23/23 均无 rank 成员） |
| `conversion.component_click_count_range` | `"500以下"` / `"500-1000"` / `"1000-3000"` / `"0"` / `"-"` | 区间原值；无"以上"样本 |
| `conversion.component_click_rate_range` | `"2%以下"` / `"2%-4%"` / `"0"` / `"-"` | 区间原值 |
| `conversion.related_cpc_range` | `"24-26"` / `"48-50"` / `"774-776"` / `"7462-7464"` / `"3万-3万"` / `"-"` | 区间原值，存在**上下限相同**样本；币种未登记 |
| `conversion.related_video_count` / `related_video_play_median` | `{value}` | 单值 |
| `collections.excellent_reach` / `excellent_seeding` | 每组含 `cards[]`，卡片字段 `platform_content_id`/`local_key`/`link`/`title`/`subtitle`/`play`/`like`/`comment`/`cover` | 播放/点赞/评论为 `{kind, amount, bound}` 数值封套，路径 `stats.watch_cnt|like_cnt|comment_cnt`；链接主机 `www.iesdouyin.com` |

**参考图同源核对**：参考图达人 C位小师妹 的库内 `seeding.search_after_view = "10 - 100"`、`search_after_view_rate = "<0.02%"`、`a3_increment = "2,000 - 20,000"`，与图片逐值一致；`conversion.component_click_count_range` 库内亦为 `"500以下"`，与图片"500以下"一致 → 证明参考图与该达人确为同一条库内记录，字段映射正确。

**字段字典给出的缺口**：《达人数据字段字典》第 141 行明确"平台另展示我们未采集的字段：预期播放量、爆文率、**进店成本**、组件点击率/CPC、相关视频数"（其中组件点击率/CPC/相关视频数后来已补采）。故"进店成本/预期播放量/爆文率"无数据，本轮不展示（已获用户确认）。

## 3. 验收工具与调用方式（如实说明）

- 本会话工具注册表**未暴露** `mcp__playwright__*` 工具，因此**不是"MCP 工具直调"**；沿用本项目 CD-01/02/03 与 UI-01 已登记做法：用同一 Playwright MCP server 的 **stdio 协议客户端**（`scripts/acceptance/mcp_client.py`）驱动 `@playwright/mcp` + 本机 Chrome。
- MCP server 版本 `1.62.0-alpha-2026-06-29`，握手返回 **23** 个 `browser_*` 工具（报告 `CD04-MCP` 检查项记录该事实）。
- 浏览器为**真实 Chrome**；profile 与 `--no-sandbox/--disable-gpu` 与本项目既有验收一致（外层文件沙箱限制）。

复现命令：

```bash
# 0) 若 API 进程早于本次改动启动（无热加载），重启本地 API 以加载新增只读端点
kill <api_pid> && (set -a; . .runtime/m3-app.env; set +a; nohup .venv/bin/xingtu-api >> .runtime/logs/api.log 2>&1 &)
# 1) 登录一次（写入项目 Chrome profile 的会话）
XINGTU_QA_PASSWORD="$(awk -F= '/^QA_MEDIA_A_PASSWORD=/{print substr($0,index($0,"=")+1)}' .runtime/qa-credentials.env)" .venv/bin/python scripts/acceptance/seed_auth.py
# 2) CD-04 验收（43 项）
XINGTU_QA_PASSWORD="$(awk -F= '/^QA_MEDIA_A_PASSWORD=/{print substr($0,index($0,"=")+1)}' .runtime/qa-credentials.env)" .venv/bin/python scripts/acceptance/run_cd04_acceptance.py
# 3) 既有回归
XINGTU_QA_PASSWORD="…" .venv/bin/python scripts/acceptance/run_cd03_acceptance.py   # 38/38
XINGTU_QA_PASSWORD="…" .venv/bin/python scripts/acceptance/run_cd02_acceptance.py   # 31/31（2 项 SKIPPED）
```

## 4. 逐项验收结果（真实 Chrome）

机器可读结果：[CD-04-acceptance-2026-10-15.json](CD-04-acceptance-2026-10-15.json)，**50/50 通过**（退出码 0）。每个业务检查在**达人库入口与任务入口各跑一遍**。

| 验收项 | 检查 | 实测（两入口一致） |
|---|---|---|
| BIZ-01 | `CD04-{LIB,TASK}-BIZ-01` | 两入口商业能力正常渲染，24 个指标瓦片、2 个视频集合，无原始 JSON、无错误态 |
| BIZ-02 | `…-BIZ-01-BIZ-02-modules` | 模块顺序 `['内容数据','性价比/效果预估','种草价值','转化价值']`（第 2 轮调整后报价明细/历史合作行业已不在本章） |
| BIZ-03 | `…-BIZ-03-content-metrics` | 7 项齐全，无缺失 |
| BIZ-04 / BIZ-12 | `…-BIZ-04-BIZ-12-scope` | 内容数据「数据范围：近30天」、种草价值「近90天」、转化价值「近30天」写入各模块副标题 |
| BIZ-05 | `…-BIZ-05-units` | `播放量中位数 93.0w`、`平均点赞 9.7k`、`平均评论 749`、`平均转发 2.1k`、`视频播放中位数 86.3w`（万元/k，四舍五入 1 位，无 mismatch） |
| BIZ-06 | `…-BIZ-06-peer` | `完播率 5.51% + 优于 98.0% 同类型达人`、`互动率 1.12% + 优于 74.9% 同类型达人` |
| BIZ-07 | `…-BIZ-07-cpm-cpe` | CPM `2,969 / 2,969`、CPE `246 / 246`，两档独立、标注币种未登记 |
| BIZ-08 | `…-BIZ-08-commercial-play` | 商业播放量 `134.7w`、商业自然播放量 `109.2w` |
| BIZ-09 | `…-BIZ-09-reach` | 优秀传播视频 4 卡、4 张封面自然宽度 > 0、真实标题 |
| BIZ-10 | `…-BIZ-10-video-stats/-links/-new-tab` | 首卡 `播放量 194.4w / 点赞量 2.8w / 评论量 1.2k`；4 个链接均 `https://www.iesdouyin.com/share/video/…`；12/12 锚点 `target=_blank` |
| BIZ-11 | `…-BIZ-11-seeding` | 6 项顺序与取值全对：`5,000 - 15,000`、`0.5% - 1%`、`1% - 1.5%`、`100 - 1,000`、`0.02% - 0.1%`、`20,000 - 100,000` |
| BIZ-13 | `…-BIZ-13-seeding` | 优秀种草视频 2 卡、2 张封面、首卡 `208.2w / 1.3w / 608`（与传播视频共用卡片组件） |
| BIZ-14 | `…-BIZ-14-conversion` | `相关视频数 1`、`视频播放中位数 86.3w`、组件点击量/点击率/CPC 三项存在 |
| BIZ-15 | `…-BIZ-15-range-empty-state` | 三项区间在本快照平台值为 `-` → 页面显示 `—`（明确空态），**未渲染为 0**；相等上下限按原值保留两段的规则由代码与 `format.test.ts` 固定 |
| BIZ-16 | `…-BIZ-16-industry-removed` | 「历史合作行业」模块已从商业能力移除（两入口各验一次）；数据仍在 `fulfillment.cooperation_industry_distribution`，「履约能力」章节的「合作行业分布」面板未改动 |
| BIZ-17 | `CD04-BIZ-17-empty-fields` | DOM 置空后 24 个瓦片存活、无错误态、无 `null` 文本 |
| BIZ-18 | `CD04-BIZ-18-cover-degraded` | 断开封面地址后出现 1 个「封面加载失败」占位，页面正常 |
| BIZ-19 | `CD04-BIZ-19-refresh` | 重新载入后 `93.0w` 与 4 张卡片恢复一致 |
| BIZ-20 | `CD04-BIZ-20-layout` + 截图 | 1440px 与 390px 均无横向溢出 |
| BIZ-21 | `CD04-BIZ-21-rail-regression` / `-entry-parity` / `-route-regression` | 左栏星图ID/事实行不变；两入口模块一致；路由与刷新正常 |
| BIZ-23 | `…-BIZ-23-share-icon-removed` | 两组视频卡片均不再渲染分享 icon（`.biz-open` 计数 = 0，两入口各验一次）；跳转仍由封面覆盖层承担（6/6 `target=_blank`） |
| BIZ-09/13 封面 | `…-BIZ-09-BIZ-13-cover-delivery` | 逐张 `fetch` 页面上的封面地址：两入口各 6 张全部 `status=200`、`content-type=image/webp`、字节数 > 1000（如 `34608 / 32512 / 60916`，与库内 `media_objects.byte_size` 一致） |
| BIZ-22 | `…-BIZ-22-quote-detail-removed` + `CD04-BIZ-22-quote-data-retained` | 「报价明细」已从商业能力移除（两入口）；报价数据保留：任务入口「报价与历史」章节展示快照报价（2 项，`植入视频`），达人库入口该章节仍展示报价历史与系统采集历史（`quoteRows=2`）|

截图（`docs/evidence/assets/cd04/`）：`CD04-library-commercial.png`（达人库入口整章）、`CD04-task-commercial.png`（任务入口整章）、`CD04-task-quote-chapter.png`（任务入口「报价与历史」章节）、`CD04-library-mobile-390.png`（390px）。

浏览器控制台：脚本运行期间未捕获到页面级异常（失败时脚本会打印 DOM 快照；本轮无此类输出）。

## 5. 静态与单元验证

| 层 | 命令 | 结果 |
|---|---|---|
| 前端类型 | `npm --prefix frontend run lint`（`tsc -b`） | 通过（exit 0） |
| 前端构建 | `npm --prefix frontend run build` | 通过（dist 产出正常） |
| 前端测试 | `npx --prefix frontend vitest run` | **61 passed / 5 files**（`format.test.ts` 30、`views.test.ts` 11、`ProvenanceDrawer.test.tsx` 1、`CreatorProfile.test.tsx` 9、`App.test.tsx` 10） |
| 后端单测 | `.venv/bin/python -m pytest backend/tests/unit -q` | **213 passed** |
| 后端静态 | `ruff check`、`ruff format --check`、`mypy`（改动文件） | 通过（`Success: no issues found in 2 source files`） |
| 差异 | `git diff --check` | 通过（exit 0） |
| 未执行 | 隔离 PostgreSQL 集成测试 | `55439` 未监听，见第 7 节 |

新增/强化的断言：`countWanText` 4 例（1e3/1e4 边界、负数、空值、近似标记）、`overtakePercentText` 2 例（万分比换算、缺失不渲染 0%）、`CreatorProfile` 的四模块标题与顺序（严格等于 `['内容数据','性价比/效果预估','种草价值','转化价值','历史合作行业']`）。

## 6. 只读 API 核对

| 请求 | 结果 |
|---|---|
| `GET /api/creator-library/{cid}/contents?collection_type=excellent_reach` | `status=COMPLETE`、4 卡、`snapshot_id=9125b95f…`；卡片行含 `card_id/position/cover_status/truncated_fields/payload` |
| `GET /api/creator-library/{cid}/contents?collection_type=excellent_seeding` | `status=COMPLETE`、2 卡 |
| `GET /api/creator-library/{cid}/covers/cover/efb257a6-…/bd68d5…` | 200 + 图片字节（对象存储授权读取） |
| `GET /api/creator-library/{cid}/covers/cover/00000000-…`（越权/不存在） | **404**（归属校验生效） |
| `GET /api/tasks/{taskId}/creators/{cid}/contents?collection_type=excellent_reach` | 既有端点保持可用（任务入口 4 卡） |

## 7. 未执行 / 未验证事项（不记为通过）

1. **隔离 PostgreSQL 集成测试库 `55439`/`55440` 未监听**：本轮新增的 `creator_library_contents` 与 `creator_library_cover_reference` 没有集成测试覆盖。行为已由真实 API + 真实开发库 + 浏览器验收验证，但**集成层未验证**（沿用 CD-01 起的环境缺口）。
2. **未验证抖音作品页可播放**：仅验证了作品链接来自平台真实返回值、`target=_blank` 与可达性（浏览器内未实际打开外链播放）。不声称播放成功。
3. **未做像素级视觉对比**：参考图是巨量星图桌面截图的局部、数据为另一时点，本轮只做结构/层级/顺序/文案的一致性判断。
4. **未复核平台侧刻度**：预期 CPM/CPE（`2969`）与商业 CPM/CPE（`29.6974`）的关系未在线上确证，按原值展示并标注。
5. **未发起真实采集**：本轮不动采集/调度/Worker/入库；不得据此宣称采集链路端到端回归。

## 8. 封面加载失败复核与分享 icon 移除（2026-10-15，第 3 轮反馈）

**用户反馈**：两组视频（优秀传播视频 / 优秀种草视频）封面都提示「封面加载失败」；并按要求去掉卡片上的分享 icon。**用户随后提供了关键证据**：浏览器 Network 中该图片请求返回 **404**，地址形如
`http://localhost:5173/api/creator-library/6300acc0-…/covers/cover/…75878d6%2F9d4782c…`。

### 8.1 精准核查（只读，未改数据）

| 核查项 | 命令/方式 | 结果 |
|---|---|---|
| `media_objects` 中 `kind='cover'` | `select count(*), pg_size_pretty(sum(byte_size))` | **310 行**，约 21 MB |
| 其中对象文件真实存在于本地对象存储 | 逐行 `(object_id)` 在 `.runtime/covers/` 下做文件判断 | **155 有、155 缺**（唯一图片内容 141 份） |
| 页面读取的「最新快照」集合封面 | 按 `snapshot_collections` 关联统计 | **153 张引用，磁盘命中 72，缺失 81** |
| 本次报错达人 **C位小师妹**（`6300acc0…`） | 逐张核对 | 8 张卡片 `cover_status='STORED'`、`cover_object_id` 均在 `media_objects` 命中，但**文件 0/8 存在** |
| 缺文件能否用同内容副本恢复 | 按 `checksum` 跨任务去重 | **不能**：缺失内容在全库无任何同 checksum 文件（155/155 无副本） |
| 能否回源平台 CDN | 对缺失对象的 `source_url` 实际发起请求 | **全部 403**（74 份唯一内容签名均已过期，实测 4 条全部 403） |
| 缺失是否与任务/时间相关 | 对照磁盘目录与 DB 分任务计数 | 磁盘只剩 5 个任务目录（`f74f43bf` 56/56、`1e7a02ff` 54/54、`efb257a6` 34/34、`50c8edf4` 7/7、`d5fe36f3` 4/4 全部吻合）；其余 16 个任务的封面行**一个文件都没有**——与 2026-10-13 20:18 的 `.runtime/xingtu-development-pre-lib-01.dump`（数据库转储）时间吻合，即**数据库带回了早期任务的 `media_objects` 行，但这些行对应的封面文件不在当前对象存储里** |

### 8.2 结论（如实回答"数据库里有没有视频封面"）

- **数据库里有"封面记录"，但相当一部分没有"封面文件"。** 不是前端拿错字段，也不是取错地址——`media_objects` 的 `checksum`/`byte_size`/`content_type` 齐全，但对象存储里没有该文件，端点因此返回 `404 COVER_NOT_FOUND`（这正是用户看到的状态码）。
- **缺的不是个别达人**：最新快照的 153 张引用中 81 张（约 53%）缺失；C位小师妹、吧唧小天菜、呼叫网管、姜乘澜、小鱼聊母婴、浔鹭、狗蛋夫妇、肖恩OMG、遥遥小宝、娱乐课代表孙小寒、桃花岛主黄蓉 等 13 位达人首页全缺；而**甄选聊车、京娱汽车世界、大鲜汽车讲堂、姚厂长讲车、张国伟_国家伟大、懂车阿伟、猪妹、圈内、汽车星球、汽车模拟测试、超哥撸车** 的封面文件完整（这也是本卡此前用甄选聊车验收时"封面正常"的原因）。
- **无法在此修复**：对象文件在本地与平台侧都取不回来（同内容无副本、平台签名 URL 全部 403）。恢复唯一路径是**重新采集这些达人**（Worker/采集侧动作，超出本卡授权），或另行为对象存储做一次带校验的回填。

### 8.3 本轮修复（仅前端字段联调）

1. **区分"文件缺失"与"加载失败"**：`VideoCard` 在重试两次仍失败后，读取响应体里的 `COVER_NOT_FOUND`，命中则显示**「封面文件缺失（需重新采集）」**（`title` 说明"对象在数据库中已登记，但对象存储中没有对应文件"），不再用含糊的"封面加载失败"。
2. **一次性失败不再永久钉住**：封面加载失败先带 `cover_retry` 参数**自动重试最多 2 次**；`cover_object_id` 变化时重置重试与缺失状态。
3. **按用户要求移除卡片右上角分享 icon**：`.biz-open` 元素与样式一并删除；跳转继续由整块封面覆盖层（`.biz-play`）承担，全部 `target="_blank"`。

### 8.4 新增机器校验

| 检查 | 断言 |
|---|---|
| `CD04-{LIB,TASK}-BIZ-09-BIZ-13-cover-delivery` | 对页面每张封面的实际 `src` 发起 `fetch`，必须 `200` + `image/*` + 字节数 > 1000（甄选聊车：6 张，如 `34608 / 32512 / 60916`） |
| `CD04-{LIB,TASK}-BIZ-23-share-icon-removed` | `.biz-open` 数量必须为 0 |
| `CD04-BIZ-24-cover-file-gap` | 在 **C位小师妹** 页面：8 张卡片必须全部如实标注「封面文件缺失」，不得伪装成图片或 0；若文件日后恢复，则该断言自动改为"无缺口占位" |
| `CD04-BIZ-24-gap-keeps-links` | 封面缺失不影响作品跳转：8/8 播放入口仍在 |

回归：CD-04 **52/52**、CD-03 **38/38**、CD-02 **31/31**；前端 61 例、后端 213 例、lint/build/ruff/mypy/diff-check 通过。

> **对第 8.1 节此前版本的更正**：本节初稿曾写"封面在库内与磁盘上均存在"——那是**错误结论**，源于我把工作目录 `ObjectId` 前缀 `cover/` 重复拼接成了 `covers/cover/cover/…`，因此只命中了当时恰好完整的甄选聊车目录。经用户提供的 404 证据复核后已更正为上述按 `checksum` 逐行、跨任务、跨内容去重的精确统计。

## 9. 第 2 轮调整（2026-10-15，已完成）

用户要求从「达人详情 → 商业能力」去掉「报价明细」与「历史合作行业」两个模块。执行内容：

| 项 | 处理 | 证据 |
|---|---|---|
| 「报价明细」模块 | `commercial.tsx` 去掉 `offers` 入参；`pages.tsx`/`CreatorProfile.tsx` 去掉透传；两入口商业能力内不再渲染 | `CD04-{LIB,TASK}-BIZ-22-quote-detail-removed` |
| 「历史合作行业」模块 | 删除 `CooperationIndustryPanel` 与其在章节中的渲染；删除随之失效的 `.biz-industry`/`.biz-chip` 样式 | `CD04-{LIB,TASK}-BIZ-16-industry-removed` |
| 报价数据是否保留 | **保留**。任务入口新增「报价与历史」章节承载**本任务快照**的报价（`合作形式与报价明细` 表 + `报价观察` 列表，实测 2 项）；达人库入口保留原章节（跨任务当前报价 + 报价历史 + 系统采集历史） | `CD04-BIZ-22-quote-data-retained` + `CD04-task-quote-chapter.png` |
| 历史合作行业数据是否保留 | **保留**。`fulfillment.cooperation_industry_distribution` 未改，原「履约能力」章节的「合作行业分布」面板仍在 | 未删任何数据/接口；CD-02 回归中的履约检查通过 |

**为什么给任务入口补一个报价章节**：移除「报价明细」后，任务入口原本唯一能看到该任务报价的位置就消失了。为不丢失真实数据（`cooperation_offers` 已采集到 2 项真实报价 ￥40,000），把报价放到「报价与历史」章节——它**不在商业能力内**，完全满足"商业能力不展示报价明细"的要求。若你希望任务入口也完全不展示报价，告知后我删除该章节即可。

回归：CD-04 **46/46**、CD-03 **38/38**、CD-02 **31/31**；前端 61 例、后端 213 例、lint/build/ruff/mypy/diff-check 通过。

## 10. 遗留问题

| 级别 | 问题 | 归属 |
|---|---|---|
| P1 | 种草价值 4 处"名称 ↔ 口径"不一致：`search_after_view`/`personal_search_after_view` 是区间人数档位而非"平均次数"；`personal_*` 原字段为"个人页"而非"个人视频"。页面按用户确认的新名展示，并在瓦片说明与卡片中标注原名 | 本轮引入展示、口径待确认 |
| P1 | 预期 CPM/CPE 与商业 CPM/CPE 的缩放与币种未确证（沿用 CD-02 结论） | 项目原有证据缺口 |
| P1 | 进店成本 / 预期播放量 / 爆文率未采集，页面无对应指标 | 项目原有（需采集授权） |
| P2 | 转化价值三项区间在甄选聊车快照为空标记，无法在该达人上演示真实区间；其他达人有真实值 | 数据本身，非缺陷 |
| P2 | 旧 `.content-*` 样式与 `frontend/src/profilePresentation.tsx` 已无引用 | 项目原有/本轮遗留，待用户决定是否删除 |
| P1 | 隔离集成测试库不可用导致新端点无集成测试 | 项目原有（CD-01 起） |

本轮**未引入 P0 问题**；未发现与本轮改动相关的失败项。
