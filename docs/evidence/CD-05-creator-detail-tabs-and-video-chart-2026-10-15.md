# CD-05 证据：达人详情 Tab 调整与「创作能力 · 最新视频表现」优化

- 日期：2026-10-15（+08:00）
- 卡片：[CD-05](../tasks/CD-05.md)
- 环境：本机真实运行栈——前端 `http://127.0.0.1:5173`（Vite dev）、API `http://127.0.0.1:8000`、
  真实开发库 `xingtu_development`（PostgreSQL 18.3，只读查询）。
- 被测达人：甄选聊车，`creator_id=700ca5b0-f0c8-4436-86fe-624dfeb0f151`，
  `root_task_id=efb257a6-476b-47ee-aff4-807795bb61a0`。
- 浏览器自动化：项目 `~/.codex/config.toml` 中登记的 Playwright MCP server（`@playwright/mcp` 1.62.0，
  `--browser chrome` + 项目独立 profile），经 `scripts/acceptance/mcp_client.py` 以 MCP **stdio** 协议调用。
  **本会话工具列表未暴露 `mcp__playwright__*`，因此这是 stdio 客户端代调，不是工具直调**；如实记录，不伪称直调。
- 报告原文：[CD-05-acceptance-2026-10-15.json](CD-05-acceptance-2026-10-15.json)

## 1. 执行命令与结果

```bash
# 前端单元测试 / 类型检查 / 生产构建
cd frontend && npx tsc -b --pretty false && npx vitest run && npm run build
# 后端回归（本轮未改后端）
.venv/bin/python -m pytest backend/tests/unit -q
.venv/bin/python -m ruff check backend/src backend/tests && .venv/bin/python -m mypy backend/src
# 真实浏览器验收
XINGTU_QA_PASSWORD=*** .venv/bin/python scripts/acceptance/run_cd05_acceptance.py
```

| 检查 | 结果 |
|---|---|
| 前端 `tsc -b`（= `npm run lint`） | 通过，无输出 |
| 前端 `vitest run` | **68 passed**（5 文件；CD-05 新增 6 例，改写 4 例） |
| 前端 `npm run build` | 通过（`dist/assets/index-*.js` 417.31 kB，gzip 130.30 kB） |
| 后端 `pytest backend/tests/unit` | **213 passed** |
| `ruff check` / `mypy` | All checks passed / no issues（31 source files） |
| `git diff --check` | 干净 |
| **Playwright MCP + Chrome 验收** | **38/38 通过**，报告 `docs/evidence/CD-05-acceptance-2026-10-15.json`；Console Errors: **0**，失败 API 请求 **0** |

## 2. 逐项验收（CRE-01 ~ CRE-22）

| 编号 | 测试内容 | 结果 | 实测证据 |
|---|---|---|---|
| CRE-01 | 达人详情仅五个 Tab | 通过 | 达人库入口 `['商业能力','创作能力','履约能力','连接用户','报价与历史']`；任务入口前四个相同（第五个沿用既有「有报价观察才显示」条件，本轮未改，见 §5.3） |
| CRE-02 | 达人概览不再显示 | 通过 | 两入口 `达人概览` Tab 不存在，`#overview` 面板不存在 |
| CRE-03 | 默认 Tab = 商业能力 | 通过 | 两入口 `active='商业能力'`、`aria-selected='true'` |
| CRE-04 | 五个 Tab 切换正常 | 通过 | 五章逐一切换，`active` 与点击一致，正文长度 619–1596 字符，均渲染真实内容 |
| CRE-05 | 旧 Tab 状态不产生空白页 | 通过 | 整页加载 `#overview` → 落到 `商业能力`、正文 1596 字符；页内改 hash → 同样落到 `商业能力`，URL 归一为 `#commercial` |
| CRE-06 | 图表正常加载 | 通过 | 15 根柱子 = API 真实 15 条记录（HTTP 200） |
| CRE-07 | 每根柱子展示对应播放量 | 通过 | 渲染标签 `['91.6万','87.0万',…,'577.5万']` 与按 API 原始 `play` 独立计算的结果**逐项完全一致**（15/15） |
| CRE-08 | 播放量按万为单位 | 通过 | ≥1万→`万`（1 位小数）、1千–1万→`k`、<1千原数；仅展示层换算 |
| CRE-09 | X 轴展示发布时间 | 通过 | `['2026-10-12','2026-10-11',…,'2026-09-19']`，不再是 1/2/3 序号 |
| CRE-10 | 日期与视频数据一致 | 通过 | 15/15 等于平台 `item_date`；库内 `item_date` 与 `utc(create_time)` 也 15/15 一致 |
| CRE-11 | 柱子 Hover 展示封面/标题/播放数 | 通过 | 浮层内容：`雨刮器为什么不好用 #汽车知识…`、`播放量 915,520`、`2026-10-12`，与第 1 根柱子对应的同一条记录一致 |
| CRE-12 | 浮层不被裁剪、可移入 | 通过 | `position=fixed`，浮层 236×216.9，`withinViewport=true`；鼠标从柱子移入浮层后浮层仍打开（`stillOpen=true`） |
| CRE-13 | 点击图表作品跳转正确链接 | 通过 | 柱子 `href` **完全等于** API 中该记录的 `url`（`…/share/video/7695691295523966970/…`），`target=_blank`，点击后仍停留在详情页；Tooltip 内链接指向同一记录 |
| CRE-14 | 下方作品封面 | 通过（降级） | 15/15 走既有「平台未提供封面地址」占位；**未构造未经验证的 CDN 地址**，原因见 §5.1 |
| CRE-15 | 下方作品点击跳转 | 通过 | 卡片 `href` 与柱子同源、`target=_blank`、点击不离开详情页；15 条链接两两不同，且每条 `href` 含**自身** `item_id` |
| CRE-16 | 视频表现口径对照已移除 | 通过 | `.compare-table` 不存在，正文不含该标题 |
| CRE-17 | 数据空值正常降级 | 通过 | 切到「最新星图视频」：有数据时渲染 6 条，无数据时走既有空态；无异常、无空白页 |
| CRE-18 | 较长标题不造成布局错乱 | 通过 | 390px 下 `scrollWidth == innerWidth == 390`，无横向溢出；柱子宽 58px、卡片宽 152px；播放量标签不裁切 |
| CRE-19 | 图表与作品列表数据一致 | 通过 | 柱子链接与卡片链接**顺序与地址完全相同**（15 vs 15），两者来自同一份规范化数据 |
| CRE-20 | 页面刷新后数据恢复 | 通过 | 刷新后默认章节仍为 `商业能力`，创作能力 15 柱、标签与日期与刷新前完全一致 |
| CRE-21 | UI 参考图还原 | **未完成** | **本轮未收到参考图片**（仓库内无对应素材），见 §5.2 |
| CRE-22 | 相关页面回归 | 通过 | 任务入口章节/图表与达人库入口完全一致；`履约能力`、`连接用户` 章节回归正常；Console Errors 0、失败 API 0 |

## 3. 字段核对（API 与页面一致）

页面渲染与同一份 API 响应逐项比对（`/api/creator-library/{id}` 的 `profile_payload.modules.creation.fields[]`
中 `recent_video_performance.value.data`，15 条）：

| 字段 | JSONB 路径 | API 字段 | 前端消费位置 | 真实示例 |
|---|---|---|---|---|
| 视频 ID | `…value.data[].item_id` | payload 原样下发 | `buildVideoItems` → `data-video-id`、链接唯一性核对 | `7695691295523966970` |
| 视频标题 | `…data[].title` / `item_title` | 同上 | 柱子 `aria-label`、浮层标题、卡片标题 | `雨刮器为什么不好用 #汽车知识…` |
| 视频封面 | `…data[].item_cover`（同 `head_image_uri`） | 同上 | 卡片 `<img>`（仅接受 http(s)）/ 占位降级 | `tos-cn-i-0813c000-ce/ownaEMiVAPe6AynMEABAIsZ6e81wlEDAAkipfP` |
| 视频播放量 | `…data[].play` | 同上 | 柱高 + 默认可见标签（万/k）+ 浮层 + 卡片 | `915520` → `91.6万` / 浮层 `915,520` |
| 视频发布时间 | `…data[].item_date`（回落 `create_time` Unix 秒） | 同上 | X 轴标签、卡片日期、浮层日期 | `2026-10-12`（`create_time=1791792758`，同日） |
| 视频 URL | `…data[].url` | 同上 | 柱子 `href`、浮层链接、卡片 `href` | `https://www.iesdouyin.com/share/video/7695691295523966970/?…` |

全库 1916 条视频记录的字段可用性（只读统计）：`url` 1916、`title` 1916、`play` 1916、`create_time` 1916、
`item_date` 1916、`item_id` 1916、`item_cover` 非空 1845（71 条为空串）。

## 4. 截图证据

| 用途 | 文件 |
|---|---|
| Tab 修改后（默认商业能力） | [CD05-library-default-tab](assets/cd05/CD05-library-default-tab.png) |
| 五个 Tab 逐一切换 | [CD05-library-five-chapters](assets/cd05/CD05-library-five-chapters.png) |
| 最新视频表现柱状图（默认播放量 + X 轴日期） | [CD05-library-latest-video-chart](assets/cd05/CD05-library-latest-video-chart.png) |
| Hover 视频信息浮层 | [CD05-library-hover-tooltip](assets/cd05/CD05-library-hover-tooltip.png) |
| 下方作品区域（封面降级 + 可点击） | [CD05-library-work-cards](assets/cd05/CD05-library-work-cards.png) |
| 390px 窄屏无溢出 | [CD05-library-creative-390](assets/cd05/CD05-library-creative-390.png) |
| 任务入口同一图表 | [CD05-task-latest-video-chart](assets/cd05/CD05-task-latest-video-chart.png) |

## 5. 遗留差异与未完成项（如实记录）

### 5.1 视频封面无法渲染：数据侧缺口，需用户决策

- **当前证据**：JSONB 中 `item_cover` / `head_image_uri` 是平台对象存储的**不透明 key**
  （`tos-cn-i-0813c000-ce/ownaEMiVAPe6AynMEABAIsZ6e81wlEDAAkipfP`），**不是**可渲染的 HTTPS 地址；
  全库 1845 条非空封面中 **0 条**是完整 URL，且从未入库对象存储（`.runtime/covers` 只有精选集合封面）。
- **对比**：精选作品卡片能显示封面，是因为其契约字段 `cover` 返回的是
  `p3-star-fe-sign.byteimg.com` 等**已签名完整外链**，由 `CoverPipeline` 受控下载入库（`contracts/douyin_xingtu.verified.json`
  的 `allowed_hosts` 也只登记了这三个 byteimg 主机）。最近视频记录**没有任何等价字段**。
- **本轮处理**：不构造未经验证的 CDN 地址（既不猜测 `douyinpic` 域名，也不越界修改采集与白名单），
  封面按既有方式降级为「平台未提供封面地址」，并在卡片与浮层如实标注。
- **影响**：CRE-14 以「降级正确」通过，但**未达成"显示真实封面"**；CRE-21 无法完成。

### 5.2 参考图片未提供

任务说明写有"以我提供的参考图片为目标布局"，但本轮对话与仓库内均未提供该参考图
（`docs/assets/` 只有 `xingtu-featured-reach.png` / `xingtu-featured-seeding.png` 两张精选集合旧图）。
当前实现依据**现有设计系统**与 CD-04 已确认的视频卡片视觉落地，间距/标签位置/浮层结构待参考图到位后校正。

### 5.3 任务入口「报价与历史」章节数（既有行为，未修改）

任务入口在**该快照确有报价观察**时渲染第五个「报价与历史」章节，否则为四章。这是 CD-04 起的既有数据条件，
本轮未改动。任务一"最终仅保留五个 Tab"与"不得修改这五个 Tab 已有业务功能"在此处存在解释空间，
按"不修改既有业务"处理；若要求任务入口恒为四章或恒为五章，需要用户明确后再改。
