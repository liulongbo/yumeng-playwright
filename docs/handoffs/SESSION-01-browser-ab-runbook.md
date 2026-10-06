# SESSION-01 子账号回退浏览器 A/B 手册

> 适用于 `unit-local-mac-02` 的本地真实账号诊断。不使用、复制或修改日常 Chrome profile。

## 不可变前置

- 三组都使用同一个系统 Google Chrome、同一邮箱/密码和同一本机网络。
- 测试期间不在其他客户端登录同一星图账号。
- 同一 profile 每次只能由一个 Chrome 进程打开。每组切换前使用 `Command-Q` 完全退出上一个 Chrome，不只关窗口。
- 不修改执行单元绑定、不写 Cookie、不启用 stealth/反检测。
- 目标账号：`1865332309937515`；非默认对照账号：`1831973402720484`；默认回退账号：`1832740070238347`。

## A：当前项目 profile，不经 Playwright

1. 停止 Worker/探针，完全退出由它们打开的 Chrome。
2. 直接启动系统 Chrome：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="/Users/yaoyao/Documents/02-Work/予梦/01-定向爬取+定时更新/.runtime/profiles/unit-local-mac-02" \
  --no-first-run --no-default-browser-check \
  "https://www.xingtu.cn/ad/creator/index"
```

3. 依次选择 `1831973402720484` 和 `1865332309937515`。每次记录：选后立即、刷新、进入达人广场、重启 Chrome 后的实际账号。
4. `Command-Q` 完全退出。

## B：新隔离 profile，先直接 Chrome，后 Playwright

1. 直接 Chrome 会自动创建下列一次性 profile：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="/Users/yaoyao/Documents/02-Work/予梦/01-定向爬取+定时更新/.runtime/profiles/session-ab-direct-first" \
  --no-first-run --no-default-browser-check \
  "https://www.xingtu.cn/ad/creator/index"
```

2. 人工登录，选中 `1865332309937515`，验证刷新和达人广场，然后 `Command-Q`。
3. 用现行 Playwright 参数打开同一测试 profile：

```bash
XINGTU_DIAGNOSTIC_HMAC_KEY="$(cat .runtime/drift-probe.hmac-key)" \
.venv/bin/python -u scripts/account_drift_probe.py \
  --config .runtime/units/local-dev-mac-02.json \
  --profile-directory-override .runtime/profiles/session-ab-direct-first \
  --rounds 1 --same-page-reads 1 --await-login-seconds 240 \
  --hold-open-seconds 900
```

4. 报告的 `browser-environment.ab_variant` 必须为 `playwright-current`。检查冷启动、进入业务页、`star_sessionid` 签发后及刷新后的账号。

## C：只移除项目两个网络启动参数

**仅当 A 成功、B 失败时执行。** 重复 B 的 Playwright 步骤，只增加：

```bash
--omit-project-network-args
```

该开关只在 `local_development` 允许，只移除：

- `--disable-quic`
- `--force-webrtc-ip-handling-policy=disable_non_proxied_udp`

它不修改 Playwright 默认参数，也不隐藏自动化。报告中的 `ab_variant` 必须为 `playwright-without-project-network-args`。

## 通过与分流

| 结果 | 结论/后续 |
|---|---|
| A 可切换，B 失败，C 成功 | 项目自定义网络参数是影响变量；评估本地模式移除，生产线路仍保持 fail-closed |
| A 可切换，B/C 均失败 | Playwright 控制环境与平台处理相关；不做 stealth 绕过，走平台默认账号/独立登录身份/人工同 Context 交接 |
| A 也失败，日常 Chrome 成功 | 项目独立 profile 的服务端业务会话或设备上下文异常；不实施自动点击修复 |
| B 中 locator 点击后稳定保持目标 | 可进入版本化 `subaccount_selection` 契约与正式 Adapter 实现门槛 |

真实验收前不得把自动选号标为可用，也不得把任何一次成功外推为长期稳定。
