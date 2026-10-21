# 真实 E2E 复验（第二次真实任务）

- 任务 ID：b5a01709-8a4b-46bd-aa31-6494b0d9ce24
- keyword：宠物；target_count：10；unit-local-mac-02；LOCAL_DEVELOPMENT
- 创建时间：2026-10-20T15:16:03Z（前端提交）
- 只创建 1 个新真实任务；未重试/取消历史任务

## P1/P2
- P1：deepseek-flash 成功，input_tokens=16073、output_tokens=88、latency_ms=1235
- FilterPlan：keyword=宠物，target_count=10，capability=xingtu-ad-creator-square-v2
- P2-1/search/profile 任务创建
- task_dispatches：collect/b5a01709... sent=true，workflow_started_at=15:16:07Z
- Workflow：CollectF04F05V1，run 01a159e2-52a2-74fa-9aef-60fbff57baf2，15:29:53Z FAILED（Activity task timed out / heartbeat）

## 采集
- 20 个搜索候选
- candidate 0：6983857505726103560，done，8 modules + excellent_reach/excellent_seeding
- candidate 1：7360610271510921225，collecting，basic only，valid=true
- task_creators：2（均 valid，latest_snapshot_id=NULL）
- creator_snapshots：0
- featured_collections：0
- featured_cards：0
- media_objects：68（新任务运行期间新增 cover）
- 前端：2 位有效、0 资料完整、0 精选、0 位可查看；任务仍“采集中”

## F10
- 本任务 challenge_count=0；无新的 verification_events / takeover
- F10 真实恢复：NOT TESTED（本轮没有滑块）

## 终态
- root_tasks：COLLECTING v135，updated_at=15:29:33Z
- execution_units：SESSION_UNVERIFIED，generation=9，owner=NULL，browser_stopped=true，last_heartbeat_at=15:29:53Z
- 无项目 Chrome 进程；Worker PID 20406 仍在线
- 未自动重试该任务
