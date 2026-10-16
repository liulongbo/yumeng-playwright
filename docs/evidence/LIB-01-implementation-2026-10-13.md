# LIB-01 实施与验证证据

时间：2026-10-13（Asia/Shanghai）  
环境：本机开发库 `xingtu_development`、隔离 PostgreSQL 测试库 `xingtu_test_creator_library`、合成前端 API。未访问星图平台、未创建采集任务。

## 实施事实

- 迁移 010 新增 `douyin_xingtu_creator_current`、`douyin_xingtu_creator_snapshot_index`、`douyin_xingtu_creator_quote_observations` 及查询索引；保留 `platform_creators.projection` 与 `creator_snapshots.payload` 原样。
- 迁移 011 将回填的 `field_sources` 收敛为观测时间、状态、来源类型、契约、路径、单位和周期等允许元数据；不向达人库详情暴露任意 JSONB 字段值。
- `Repository.persist_creators()` 在发布快照的既有事务内同步达人库读模型；非 `COLLECTED` 字段不清空最近成功当前值。
- 新增认证 API：列表、详情、历史、报价；React 路由为 `/creators` 与 `/creators/{creator_id}`。

## 数据库迁移与回填

在迁移前创建了本机开发库可恢复备份（位于受忽略的 `.runtime/`，不入版本库），随后执行：

```text
XINGTU_DATABASE_URL=… make migrate ENVIRONMENT=development
```

结果：成功应用 010、011。随后以 `BEGIN READ ONLY` 核验：

| 核验项 | 结果 |
|---|---:|
| `schema_migrations` 最大版本 | 11 |
| 当前达人库索引行 | 21 |
| 带可筛选粉丝值的当前索引行 | 12 |
| 历史快照索引行 | 42 |
| 报价观测行 | 231 |
| 仍含旧 `basic.followers` 来源键的行 | 0 |

该查询只读执行，未修改既有 JSONB、不可变快照或任务结果。

## 自动化验证

| 命令/检查 | 结果 |
|---|---|
| 隔离库 `pytest backend/tests/integration/test_creator_library.py backend/tests/integration/test_repository.py -x` | 30 passed |
| `make test-unit`（本轮最后复跑） | 188 passed / 1 failed：`test_stable_window_resets_after_challenge_flicker_without_page_actions` 在 `ChallengeHandler.wait_for_stable_session` 超时；`challenge.py` 属本任务开始前已有的并行改动，非达人库路径。本任务此前一次单元运行曾为 189 passed，但该结论不覆盖并行修改后的代码。 |
| `make frontend-check` | TypeScript 通过；Vitest 4 passed |
| `make frontend-build` | Vite 生产构建通过 |
| `make lint && make typecheck && make format-check` | 全部通过 |
| `git diff --check` | 通过 |

集成覆盖：登录门禁、列表行业/类型/粉丝/合作形式筛选、原始值与近似原文、详情字段来源、历史、报价、发布事务写入，以及失败字段不覆盖最近成功值。

## 未覆盖项

- 本轮没有 Lazyweb MCP；依项目规范未伪造 UI 调研或视觉报告。
- 新页面已通过合成 API 前端测试和生产构建，但尚未在重启后的本地产品 API/浏览器中做人工视觉验收；这不影响迁移及 API 的开发库验证。
- 当前全量单元回归有一项并行挑战模块失败，需由该模块负责人修复并复跑；LIB-01 不将其伪报为通过。
