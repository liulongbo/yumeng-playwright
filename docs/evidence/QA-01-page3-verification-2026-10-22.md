# QA-01 page=3 真实检索核验（2026-10-22）

> 范围：真实 Chrome + unit-local-mac-02 受控 Profile，keyword-only 搜索；复用 page1 原生请求头/请求体，在同一认证上下文发起 page=1/2/3 真实请求。未创建任务、未采集达人、未写业务库。

## 1. 方法

- 使用 BrowserRuntime 打开受控 unit profile，session 核验 VALID / PROTECTED_PAGE_AND_ACCOUNT_VERIFIED。
- 进入 https://www.xingtu.cn/ad/creator/market，关键词“户外”触发 page1 搜索；捕获该请求的 JSON body 与可复用 headers（过滤 cookie/host/origin/referer/user-agent/sec-*）。
- 在同一页面上下文用 fetch 依次请求 page=1、2、3；只记录 HTTP 状态、pagination.page、has_more、authors 数量与 star_id 列表；不保存完整响应体/headers。
- 未修改账号、Cookie、Profile；验证后 Chrome 正常关闭。

## 2. 结果

| 页 | HTTP | pagination.page | has_more | authors |
|---|---|---|---|---|
| 1 | 200 | 1 | true | 20 |
| 2 | 200 | 2 | true | 20 |
| 3 | 200 | 3 | true | 20 |

- page3 的 20 个 star_id 与 page1/page2 列表不同（本次三页 ID 无重复）。
- 说明 page=3 的页面内请求复用真实可用；当前 page_fetch_max_verified 可由 2 提升到 3。
- page=4 及以后、真实平台终点仍未核验；不能开启 page_fetch_continuous_verified。

## 3. 契约变更

- contract_version：xingtu-ad-creator-featured-v11 → v12。
- search.page_fetch_max_verified：2 → 3。
- search.page_fetch_continuous_verified：保持 false。
- coverage_gaps 更新为 page=2/3 已核验、page=4+ 与终点未核验。
- evidence_refs 增加本证据。
- 未改 adapter_version、capabilities.version、Schema、迁移或数据库。

## 4. 边界

- 本次只证明搜索页 3 可取得真实候选，不等于 target=41 产品任务已完成；target=41 的真实采集仍需单独授权与成本评估。
- 目标 21 的当前产品分页验收见[QA-01 target=21 分页证据](QA-01-pagination-2026-10-22.md)。
- 未提交 Git。
