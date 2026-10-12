# CHALLENGE-01 实施与验证证据（2026-10-10）

## 实施结果

本轮已完成安全验证托管的后端主链路：新增独立 `ChallengeHandler`，将挑战从普通登录等待中拆分为 `WAITING_FOR_VERIFICATION`／`NEEDS_VERIFICATION`，并在同一 BrowserHost、Context、Page 和租约内进行只读等待。处理器不会点击、拖动或操作任何验证控件；挑战期间采集引擎不执行导航、搜索、模块、精选集合或封面动作。

恢复要求挑战元素连续 5 秒不可见，同时保护页、当前账号、绑定账号和 `SessionHealth` 全部有效。挑战重新出现会重置稳定窗口。默认限制为单达人 1 次、根任务 2 次成功恢复，单次等待 15 分钟，恢复后冷却 60 秒，达人间隔至少 15 秒；超限、超时、账号不一致或登录失效均发布已有结果并以 `PARTIAL_COMPLETED` 收尾。

检查点新增挑战次数、恢复次数、当前达人、挑战状态和请求观测字段，全部有旧值默认值；未新增数据库表或迁移。恢复路径在导航和精选集合重载前检查既有成果，完整达人、模块及精选集合直接跳过，已存封面随完整集合复用。

产品查询 API 已输出安全验证摘要和用户可读终止原因。续作轮次已补齐产品任务详情页的 `WAITING_FOR_VERIFICATION` 状态、验证托管摘要面板、等待时长、当前达人、恢复次数、监测状态、终止原因和已交付说明；本次仅接入既有后端字段和状态体系，未重新设计产品页面。Lazyweb MCP 工具在续作会话仍不可用，因此未生成 Lazyweb 报告。

## 续作恢复审计与补齐（2026-10-10T21:29+08:00）

恢复审计确认：上次开发已完成后端挑战托管主链路、状态/检查点字段、部分完成、产品查询摘要、官方 API 能力矩阵和专项测试；中断点主要在产品详情页展示和完整回归。续作未重写后端主链路，只做最小增量：

- `frontend/src/types.ts`：新增 `WAITING_FOR_VERIFICATION` 与 `ChallengeSummary` 类型。
- `frontend/src/status.ts`：新增等待安全验证标签、等待态和告警色。
- `frontend/src/pages.tsx`：任务列表筛选纳入等待验证；任务详情新增安全验证托管面板；进度轨道和任务说明支持等待验证。
- `frontend/src/styles.css`：新增验证托管面板样式，沿用现有 M3 控制台视觉系统。
- `frontend/src/App.test.tsx`：新增任务详情等待验证场景，覆盖挑战摘要渲染。
- `backend/src/xingtu/product_queries.py`：仅修复两处超长中文行以满足 ruff，不改变产品摘要行为。

## 自动化验证

| 验证层 | 命令／范围 | 结果 |
|---|---|---|
| 静态检查 | `ruff check`、`ruff format --check`、`mypy`（挑战相关后端文件） | 通过 |
| 单元测试 | `pytest backend/tests/unit` | 164 passed |
| Browser Contract | `make test-contract` | 28 passed |
| 专项 PostgreSQL 集成 | `backend/tests/integration/test_challenge.py` | 2 passed |
| 既有相关 PostgreSQL 集成 | Repository、Engine、Featured、M3 Product | 64 passed，1 failed |

续作轮次重新执行并取得以下结果：

| 验证层 | 命令／范围 | 结果 |
|---|---|---|
| 后端静态 | `.venv/bin/ruff check backend conftest.py tests scripts` | 通过 |
| 后端格式 | `.venv/bin/ruff format --check backend conftest.py tests scripts` | 62 files already formatted |
| 后端类型 | `.venv/bin/mypy backend/src` | 通过，28 source files |
| 后端单元 | `.venv/bin/python -m pytest backend/tests/unit -q` | 164 passed |
| Browser Contract | `PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers .venv/bin/python -m pytest backend/tests/contract -q` | 28 passed；沙箱内因 macOS Mach port 权限失败，沙箱外同代码通过 |
| 挑战专项集成 | `XINGTU_TEST_DATABASE_URL=postgresql://xingtu_test@127.0.0.1:55439/xingtu_test_f04f05 .venv/bin/python -m pytest backend/tests/integration/test_challenge.py -q` | 2 passed；沙箱内 localhost TCP 被拒，沙箱外通过 |
| 后端集成回归 | 同一隔离测试库运行 `backend/tests/integration -q` | 67 passed、1 skipped |
| E2E 回归 | `PYTHONPATH=. PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers XINGTU_TEST_DATABASE_URL=... XINGTU_TEMPORAL_TEST_BINARY=.runtime/temporal-test/temporal-v1.9.1 .venv/bin/python -m pytest tests/e2e -q` | 7 passed |
| 前端类型 | `npm --prefix frontend run lint` | 通过 |
| 前端单测 | `npm --prefix frontend test` | 3 passed |
| 前端构建 | `npm --prefix frontend run build` | 通过 |

首次实现轮次记录过既有 `test_target_20_and_200` 的 200 人合成长跑在约 122 秒发生 `LEASE_LOST`；续作轮次的完整 `backend/tests/integration` 已在同一隔离测试库通过 67 项、跳过 1 项，未复现该失败。

专项测试已覆盖：挑战闪烁重置 5 秒窗口、超时、登录失效、账号不一致、达人级恢复上限、旧检查点默认值、执行单元释放为 `NEEDS_VERIFICATION`、产品安全摘要和完整精选集合在页面重载前跳过。

## 尚未完成的验收

1. 真实平台自然触发下的等待期零业务请求、同一页面自动恢复、一次恢复只增加一次 `session_version` 和终态请求停止证据。
2. 真实或可比基线下的重复关联请求降低至少 50%；当前已有路径级跳过及计数能力，尚无可比运行样本。
3. 官方 API 是否覆盖 F05 81 字段与两组精选集合仍待企业账号权限目录核验；当前运行时不依赖未验证接口。

本轮未主动制造平台风控，未实现滑块破解、轨迹模拟、OCR／打码、隐身伪装、代理／账号轮换、签名逆向或私有接口调用。
