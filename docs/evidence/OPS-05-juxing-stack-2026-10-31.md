# OPS-05 磁力聚星隔离全栈启动与页面验证（2026-10-31）

- 时间：2026-10-31 01:02—01:08（Asia/Shanghai）
- 代码状态：分支 `快手_1026`，工作区含既有未提交改动；本轮未改业务代码
- 运行模式：聚星隔离栈（测试库，独立 Temporal/API/前端/Worker/Profile）
- 任务卡：[OPS-05](../tasks/OPS-05.md)
- 用户要求：启动磁力聚星爬取等服务，网站上可以完整体验聚星采集流程

## 1. 为什么用隔离栈

主站 `http://127.0.0.1:5173/` 的 `/api/platforms` 返回 `kuaishou_juxing.enabled=false`，主库 `xingtu_development` 只有 `unit-local-mac-02` 的星图绑定，没有聚星账号/Profile。直接在主站开启 Flag 会向主业务库写入聚星任务与达人数据，与 KJX-01「生产 Flag 关闭、正式业务库未写入聚星数据」的边界冲突。

项目此前为聚星准备了完整隔离栈：独立测试库 `xingtu_test_kjx_regression`、独立 Temporal `57235`、独立 API `4192`/Vite `4193`、执行单元 `unit-local-mac-02-kjx-full`、聚星绑定 `60821564`、独立 Profile 与会话快照。本轮复用它。

## 2. 启停入口

新增 `.runtime/kjx-full/stack.sh`（gitignored，0700）：

```bash
./.runtime/kjx-full/stack.sh up       # Temporal + API + intake + collection + Vite
./.runtime/kjx-full/stack.sh status
./.runtime/kjx-full/stack.sh stop
./.runtime/kjx-full/stack.sh restart
```

脚本从 `.runtime/kjx-full/regression/env` 加载隔离配置，并从 `.runtime/deepseek.env` 补充模型密钥；使用独立 PID 文件 `.runtime/kjx-full/regression/pids.tsv`。

首次启动时 intake 退出：

```
httpx.InvalidURL: Invalid port: ':1]'
```

原因是本机 `no_proxy` 含方括号 IPv6（`[::1]`），httpx 0.28 无法解析。与 `scripts/dev.sh` 一致，在脚本 `load_env` 中移除方括号项后重启成功。未修改仓库代码。

## 3. 进程与端口

| 服务 | PID | 结果 |
|---|---|---|
| Temporal | 75877 | `57235` 监听 |
| API | 75897 | `4192`；`/api/auth/me` 401 |
| Intake Worker | 75916 | `xingtu-intake` 在线 |
| Collection Worker | 75925 | `xingtu-unit-local-mac-02-kjx-full` 在线，`generation=6` |
| 前端 Vite | 75953 | `4193` → 200 |

队列检查：

```
xingtu-intake                       alive=True fresh=1 entries=1
xingtu-unit-local-mac-02-kjx-full   alive=True fresh=1 entries=1
```

测试库 `55439` 保持运行；主站 8000/5173 四进程未变，`update-scheduler` 未运行。

## 4. 平台与会话

- `/api/platforms`：
  - `douyin_xingtu` `enabled=true`
  - `kuaishou_juxing` `enabled=true`，`capability_status=verified`，`contract_version=juxing-video-creator-stage-c-v3`
- `/api/platforms/kuaishou_juxing/capabilities`：`capability_version=juxing-video-square-stage-c-v2`，字段包含内容关键词、38 个内容类目、粉丝数、地域、三档视频报价等。
- 会话：`execution_unit_platform_bindings` 中聚星最近观测 `VALID`（2026-10-30 22:52，`PROTECTED_PAGE_AND_URL_ACCOUNT_VERIFIED`）；`verification_events` 无 OPEN/ACKNOWLEDGED。
- 测试库数据：6 条任务（4 聚星 / 2 星图），37 位聚星达人；最近聚星任务 `56efbba5-d267-44a2-824a-2ba4e60f2dd9` 为 `COMPLETED 22/22/22`。

## 5. 页面验证

Playwright + 项目 Chromium（headless，1440×960）访问 `4193`：

1. 使用 `kjx-regression-media` 登录 → `/tasks`；
2. 任务中心显示聚星任务；
3. 点击「创建任务」→ 选择「磁力聚星」：
   - 平台选项 `disabled=false`，显示「已验证可用」；
   - 表单渲染「已核验能力版本 juxing-video-square-stage-c-v2 / 7 项条件可用」，含关键词、38 类目、粉丝、地域、报价、目标数；
4. `/creators?platform=kuaishou_juxing`：
   - 标题「磁力聚星达人」；
   - 「20 位已加载」，首位「幸福小土豆（母婴待产包）」；
   - 指标按聚星原始口径显示（粉丝、月涨粉率、互动/完播、播放中位数）。

截图（私有，未入 Git）：`.runtime/kjx-full/regression/ops05/01-tasks.png`、`02-juxing-form.png`、`03-juxing-library.png`。

控制台唯一错误是登录前的预期 `401 /api/auth/me`；登录后无失败 API。

## 6. 双栈 Worker 识别修复

两栈同时运行后，主站 `./dev.sh status` 把聚星栈的同名 Worker 误判为「重复运行」：

```
intake-worker       重复运行 2 个 pid：69701 75916（需修复，./dev.sh restart）
collection-worker   重复运行 2 个 pid：71225 75925（需修复，./dev.sh restart）
```

原 `worker_pattern` 只匹配 `xingtu-product intake-worker` / `xingtu worker --config`，未限定执行单元；`reconcile_worker` 会保留一个并结束其余，因此 `./dev.sh up/restart` 会误杀聚星栈 Worker。

修复：`scripts/dev.sh` 的 `worker_pattern` 增加 `--unit-config "$UNIT_CONFIG"` / `--config "$UNIT_CONFIG"`，只识别本栈执行单元；同步 gitignored 的 `.runtime/dev-no-upd.sh`。验证：

```bash
bash -n scripts/dev.sh
bash -n .runtime/dev-no-upd.sh
./dev.sh status
./.runtime/dev-no-upd.sh status
```

两者均只显示主站 `intake-worker` 69701 / `collection-worker` 71225，聚星栈 75916/75925 未被计入；两栈进程均保持运行。该改动是 tracked 脚本变更，未运行自动化测试套件（仓库没有 shell 脚本测试），仅做语法检查与实际双栈 `status` 行为验证。

## 7. 未执行与限制

- 未代替用户提交新的真实聚星采集任务；页面表单与 Worker 已就绪，真实采集由用户点击「创建任务」触发。
- 未验证重启后的聚星会话是否仍可用（只读记录显示上次 `VALID`）；首个真实任务若遇到子账号选择/登录/挑战，按页面提示或既有维护流程处理。
- 聚星栈使用测试库与测试账号，数据与主站隔离；主站聚星入口仍关闭。
- 本轮仅改 `scripts/dev.sh` 的 Worker 识别，未运行测试套件；已做语法检查与双栈 `status` 行为验证。
- 启停脚本位于 `.runtime`（gitignored），不是仓库命令；如需长期入口应另立任务纳入版本控制。
