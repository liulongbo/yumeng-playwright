# QA-01 新发现 1/2/3 修复与验证（2026-10-22）

> 范围：小数范围输入、结构化筛选回读、page=3 检索能力。真实 Chrome/unit 受控 Profile；未改 Schema/迁移/数据库；未提交 Git。

## 1. 小数范围输入与 0.5

### 前端

- frontend/src/pages.tsx 的 RangeInputs 两个输入增加 step=any，浏览器默认 step=1 不再阻断小数。
- frontend/src/App.test.tsx 增加断言：所有“下限”输入 step=any；前端测试 83 passed，build 通过。

### 真实平台行为

| 场景 | 页面选中区 | 最终请求 | 平台响应 |
|---|---|---|---|
| 粉丝量级 12.5w–25.5w | 粉丝数量：12.5w-25.5w | follower__ge=125000、follower__le=255000 | 200、authors=20 |
| 连接用户数 0.5w–2w | 连接用户数：2w以下 | link_link_cnt_by_industry__ge=0、le=20000 | 200、authors=20 |
| 连接用户数 0.5w–2w（读回） | 读回期望 0.5w 缺失 | — | — |

- 结论：粉丝量级支持小数；连接用户数组件会把 0.5w 截断为 0（页面显示 2w以下），无法表达 0.5w。
- 为避免静默执行错误条件，ConnectionUsersRequirement 增加“整 w”校验：连接用户数 min/max 必须是整数 w；0.5 会在 API 422 明确拒绝。粉丝量级仍允许 Decimal。
- 单测覆盖：connection 0.5 拒绝、followers 12.5–25.5 接受。
- 说明：A-10 首个任务 8bd61ffd 因 API 仍加载 v11、Worker 已是 v12 而 VERSION_MISMATCH（0 请求，环境版本对齐问题）；第二个 fc98aea2 在加入整 w 校验前被新读回以 SELECTED_MISSING:0.5w 拦下（正确 fail-closed）。两次均未产生候选/快照，未重试。

## 2. 结构化筛选回读

- adapter.py 新增 _condition_readback_tokens 与 readback_conditions：
  - 检查计划中每个字段标签、已选选项标签、区间数字 token（数字边界匹配，10w 不会匹配 100w）。
  - 拒绝计划外的已知业务字段（如计划只有连接用户数却出现粉丝数量）。
  - 不匹配抛 PLATFORM_CONDITION_MISMATCH，在最终搜索前失败；最终请求 attribute_filter 仍是值的权威门禁。
- 字符串/区间字段的回读范围：
  - 背景：性别、学历、黄 V、地域字段标签；选项标签。
  - 连接用户数：字段标签 + 计划中填写的 min/max w token。
  - 粉丝量级：粉丝数量标签 + 计划中填写的 min/max w token。
  - 观众/粉丝画像：字段标签 + 每个已选项标签。
  - 地域的具体省市值不回读，仍由最终请求 city/province 精确多重集核验。
- 测试：contract 37 passed；真机探针 min_only、background、viewer、followers_decimal 均 readback PASS；A-07 产品任务 478fa8ac（v11）与 c37ee17b（v12）均通过读回并正常收口。
- 未执行每次真实任务的独立读回失败注入；由 contract 测试覆盖缺 token / 额外字段。

## 3. page=3 检索能力

- 真机探针：page1/2/3 均 HTTP 200、authors=20、pagination.page 1/2/3、has_more=true；三页 star_id 无重复。
- 契约：contract_version v12；page_fetch_max_verified=3；page_fetch_continuous_verified=false；coverage_gaps 更新为 page2/3 已核验、page4+ 与终点未核验。
- 合约守卫测试已加入；unit 306 passed、contract 37 passed。
- API/Intake/Collection Worker 已按 v12 重启并完成新任务 c37ee17b（v12、readback、valid 1、PROFILE_SCOPE_INCOMPLETE）。
- 边界：page=4+ 与 target=41 真实产品任务未执行；不能宣称 41 已完成。

## 4. 运行态

- API 77866、intake 78544、collection 80738（启动后已验证队列）；单元 READY。
- 未提交 Git。
