# DEP-02：前端生产构建与宝塔 Nginx

状态：已完成
更新时间：2026-10-19
是否验收：是；第一阶段模板、构建及语法验证通过，腾讯云 HTTPS 实机验收另行执行。

## 目标与范围

提供 React/Vite 生产构建和宝塔 Nginx 模板，支持同源 API、WebSocket、HTTPS Cookie 与严格 Origin/CORS。

## 验收清单

- [x] 前端 production build 通过。
- [x] Nginx 模板支持 SPA、`/api` 与 WebSocket，并只代理本机 API。
- [x] 内部基础设施端口不经 Nginx 暴露。

## 验证证据

- 2026-10-18：开始实施，未修改现有业务页面语义。
- 2026-10-19：前端 build 通过（1744 modules）；83 项前端测试通过。Nginx 1.29.3 容器配临时自签证书执行 `nginx -t` 成功；模板未转发任何基础设施管理端口。

## 状态历史

- 2026-10-18：待办 → 进行中。
- 2026-10-19：进行中 → 已完成；云端域名、证书、Cookie 与 WebSocket 实机验收不在本轮冒充完成。
