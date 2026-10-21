# P1FIX-01：P1 需求转换 402 阻断修复与实机验证

状态：待验收
更新时间：2026-10-20T21:45:00+08:00
是否验收：否；修复与实机验证完成，等待 DSH 独立复测及用户验收。

## 目标与范围

定位并解除 DSH QA-01 报告的 P1 阻断：正式环境任务创建后需求转换失败
（`AI_AUTH_OR_QUOTA / provider rejected credentials`），使真实任务可以通过 P1 并进入合法的
QUEUED/资源等待状态，同时不启动 Chrome、不访问巨量星图。

本轮不做：真实采集、数据库 Schema 迁移、生产线路/租约规则修改、HTTP 80/证书/P2-P3 界面修复、
Git commit/push/merge。这些另行登记。

## 根因

- 供应商在 2026-10-20T12:36:21Z 对 `POST https://api.deepseek.com/responses` 返回
  **HTTP 402 Payment Required**，不是 401/403，也不是模型名或 Base URL 错误。
- 先前“DeepSeek 校验 200”来自 `verify_model()` 的 `GET /models`：该接口只列模型，不校验推理计费。
- 代码把 401/402/403 统一映射为 `AI_AUTH_OR_QUOTA / provider rejected credentials`，导致
  “余额不足”被误报成“凭据被拒”，是本次诊断被误导的直接原因。
- 当前账户 `GET /user/balance` 为 200、`is_available=true`，余额 8.49 CNY；
  同一套配置的真实推理与完整 P1 转换已成功。余额由 0/不足变为可用的具体时间无法由 API 证明，
  需要在 DeepSeek 控制台核对充值/扣费记录。

## 代码修复

- `backend/src/xingtu/intake.py`
  - 402 → `AI_QUOTA_EXHAUSTED`（provider_status=402，provider_detail 记录供应商错误摘要）
  - 401/403 → `AI_AUTH_REJECTED`
  - 4xx/5xx/429 均记录 provider_status/provider_detail，便于后续定位
  - `model_runs.error_payload` 增加 `provider_status`、`provider_detail`（不记录密钥）
  - 新错误码加入不可修复集合与模型错误集合，避免无意义重试
- `backend/tests/unit/test_intake.py`
  - 401/402/400 分类测试；model_runs 持久化 provider 字段测试

## 部署

- 新镜像：`xingtu-app:20261020-p1fix-wip`
  （ID `sha256:aff2c94432b9018da514a4a3ed139590edc0d58a039697947017b2d63a3e16d5`，
  基于 `xingtu-app:20261019-5182c09-wip` + 单文件补丁）
- `production.env` 已更新并备份为 `production.env.bak.20261020-p1fix`
- 重建 api / intake-worker / update-scheduler；数据库、Temporal、Redis、MinIO 未重启
- 未执行迁移；未修改历史任务 `1cfaecbc...`
- 完整 Dockerfile 构建因 PyPI `pip install uv` 超过 13 分钟未完成而中止，改用可追溯的派生镜像；
  后续需在 PyPI 可达时用 `deploy/Dockerfile.app` 重建并记录 digest

## 验收清单

- [x] 确认 DeepSeek 配置来源、模型、Base URL、容器注入一致，无重复/旧 Key。
- [x] 确认供应商失败为 HTTP 402，而非 Key/模型/URL 错误。
- [x] 修复 402/401/403 与模型调用的错误分类和持久化诊断字段。
- [x] 单元/契约/类型/lint/前端测试/前端构建通过。
- [x] 正式运行镜像中实际执行一次完整 P1 模型调用并成功。
- [x] 隔离测试任务 `8bf44ae4-cc15-4bc8-819a-5d0664cdce17` 通过 P1，进入 QUEUED/等待采集资源。
- [x] 测试窗口内无 Chrome 启动、无巨量星图访问、无浏览器租约。
- [x] 历史 FAILED 任务与数据保持完整；无删除、无 Schema 变更。
- [x] 测试任务已取消，Mac Worker 已恢复（PID 14961，poller 新鲜）。
- [ ] `backend/tests/integration`：缺少 `XINGTU_TEST_DATABASE_URL`，本轮未执行（不是代码失败）。
- [ ] DSH 独立复测（用户安排）。
- [ ] 真实 P2 采集/Chrome/星图访问（需单独授权）。

## 验证证据

- 报告：[P1-intake-fix-2026-10-20.md](../evidence/P1-intake-fix-2026-10-20.md)
- 证据目录：[P1-intake-fix-2026-10-20](../evidence/P1-intake-fix-2026-10-20/)
- 关键记录：任务 `8bf44ae4-cc15-4bc8-819a-5d0664cdce17`；model_runs 16073/88 tokens、1116ms；
  intake/collect workflow COMPLETED；执行单元 `browser_stopped=true`、generation=0、无 owner。
- 工具：现有 SSH ControlMaster、真实产品 HTTPS API、系统 Chrome + Playwright MCP（UI 截图）。

## 交接与下一步

- 等待 DSH 按 QA-01 用例独立复测 P1；复测前不要用真实任务验证 P2，避免启动 Chrome/访问星图。
- **不要直接重试历史任务 `1cfaecbc...`**：它仍允许 retry，P1 成功后可能立即派发 P2/启动 Chrome；需先隔离。
- 真实 P2 采集需单独授权；建议在授权窗口内使用测试任务并保留完整证据。
- 后续任务见 [FOLLOW-01](FOLLOW-01.md)：HTTP 80/证书、P2/P3 文案、安全响应头、镜像可复现构建、
  管理员密码轮换。
- 本轮未执行 Git commit/push/merge；工作区保留全部改动。

## 状态历史

- 2026-10-20：待办 → 进行中；开始定位 P1 402 与错误映射问题。
- 2026-10-20：进行中 → 待验收；完成 402 分类修复、镜像部署、真实 P1 转换与无 Chrome 验证。
