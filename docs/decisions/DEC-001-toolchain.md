# DEC-001：工程工具链与版本锁定

- 日期：2026-09-26
- 状态：已采纳（本轮实现范围）

## 待解决问题

技术方案第 3.2 节要求前端、会话组件、模型供应商、依赖管理、测试与静态检查工具在开发前用决策记录锁定；规范第 3.1 节要求所有计划命令可真实执行并传播失败退出码。

## 选择

| 方面 | 选择 | 版本约束 |
|---|---|---|
| 运行时 | Python | `>=3.13,<3.14`（本轮 3.13.5） |
| 依赖管理 | uv + `uv.lock`，`uv sync --frozen` | `.bootstrap/bin/uv` |
| 领域校验 | Pydantic v2 严格模型（`extra=forbid`、`validate_assignment`） | `>=2.11,<3` |
| 存储 | psycopg 3 + PostgreSQL 18 | `>=3.2,<4` |
| 编排 | Temporal Python SDK（Workflow + Activity 分离） | `>=1.12,<2` |
| 浏览器 | Playwright + 官方 Chromium（持久化上下文） | `>=1.55,<2` |
| 对象存储 | boto3 / S3 兼容（MinIO）；离线用本地文件实现 | `>=1.40,<2` |
| 静态检查 | ruff（lint + format）、mypy `strict` | `ruff>=0.12,<1`、`mypy>=1.17,<2` |
| 测试 | pytest + pytest-asyncio（`asyncio_mode=auto`），分 unit/contract/integration/e2e | `pytest>=8,<9` |
| 部署编排 | Docker Compose（`deploy/compose.yaml`） | Compose v2.40.3 |

## 主要替代方案与否决理由

- Celery / Kafka / RabbitMQ：规范明确不引入。
- 直接依赖第三方爬虫框架（Scrapy 等）：与"浏览器交互 + 响应观察"的既定主路径不符，且会隐藏请求关联语义。
- 随机 User-Agent、隐身驱动、代理轮换：规范禁止。
- 会话组件/前端框架：属于 U01，本轮不涉及产品 API 与前端，未选定；不影响本文的领域与适配器契约。

## 兼容性与限制

- 前端选型未定不阻塞后端契约；`xingtu` CLI 是内部验收入口，不对外提供提交 API。
- `mypy files = ["backend/src"]`：测试不参与类型检查；`ruff` 覆盖 `backend`、`tests`、`scripts`、`conftest.py`。
- 依赖升级必须同时更新 `uv.lock` 并重跑全部检查，禁止浮动版本。
