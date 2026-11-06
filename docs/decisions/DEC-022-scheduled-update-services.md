# DEC-022：定时更新按 (platform, creator_scene) 分组，单调度器 + 独立开关

- 日期：2026-11-06
- 状态：已实施（2026-11-06 隔离库真实四组/开关/双场景/取消/重启验收通过；CONDITIONAL GO）
- 关联：UPD-01、UPD-04、UPD-05；LIVE-02、LIVE-02G、LIVE-03；KJX-01；DEC-017、DEC-018

## 待解决问题

现有 `creator_update_schedule` 以 `creator_id` 为主键，`CreatorUpdateService.scheduler_tick` 只查
巨量星图短视频当前表、只加载一个 registry；因此无法为巨量星图直播、磁力聚星短视频、磁力聚星直播
建立独立计划，也无法让运营按平台/场景独立启停。同一达人既可能有短视频资料也可能有直播资料，必须
避免计划、快照、当前投影和失败状态互相覆盖。

## 选择

1. **扩展现有表**：`creator_update_schedule` 增加 `creator_scene`，主键改为 `(creator_id, creator_scene)`；
   周期、退避、单活跃批次、in-flight 去重和终态 reconcile 语义全部沿用，不新建第二套计划表。
2. **单 scheduler 进程、多 scope**：一个 `update-scheduler` 加载四个 `(platform, scene)` 的 registry 与
   目标定位，逐组建批；每组一个 SAVEPOINT，单组失败不影响其他组；每组最多一个非终态批次。
3. **四组独立开关**：新增 `creator_update_service(platform, creator_scene, enabled)`，迁移默认只开启
   巨量星图短视频；其他三组默认关闭。开关只控制新自动批次，不影响普通采集/手动更新。
4. **调度器心跳**：新增 `creator_update_scheduler_heartbeat`；管理页的“生效”要求开关 + 心跳新鲜 +
   契约可用，避免把“开关打开”误报为“正在自动更新”。
5. **worker 启动闸门**：`scheduled_update` 在拿浏览器前检查开关，关闭则 `CANCELLED/
   UPDATE_SERVICE_DISABLED`；计划行只释放、不计失败，重新开启后仍按原周期到期。
6. **聚星短视频定位持久化**：`platform_creators.video_homepage` 保存已验证详情 URL（userId→starId），
   历史行由一次性回填脚本从 checkpoint 补齐；未补齐的达人不纳入计划并在管理页披露。
7. **全局控制仍是调度器进程**：不新增第二个全局数据库开关；实际生效 = 进程运行 + 分组开启 + 契约可用。

## 主要替代方案

- **四套独立调度器/队列**：违背统一任务中心与单执行单元池，运维和资源竞争更难控制，排除。
- **新建四张计划表**：重复 in-flight/reconcile/退避逻辑，排除。
- **只在 API 关闭时批量取消 queued 任务**：存在“已创建但未执行”的竞态；worker 启动闸门是最终边界，
  且不打断运行中任务，采用。
- **把聚星视频计划改为按 starId 建主键**：会改变身份模型并影响历史数据，排除；只持久化导航定位。
- **用全局数据库开关替代进程控制**：会让“调度器是否运行”与“是否允许自动更新”混为一谈，保留进程级
  全局控制，新增分组开关。

## 兼容性与影响

- 迁移 022 只新增列/表/索引；旧计划行保留并解释为 `video_square`。
- 旧代码的 `INSERT ... ON CONFLICT(creator_id)` 在复合主键下不再匹配，回滚应用前必须回滚迁移或清理直播行。
- 星图短视频周期、退避、批大小、优先级、手动更新行为不变；手动聚星短视频更新仍不支持（本任务不扩展）。
- 手动直播更新仍不写计划表；其终态现在也会触发一次空 reconcile，属于幂等空操作。
- 新增管理页复用现有认证、CSRF、审计和样式，不重做调度后台。

## 验证

- 迁移/集成/单测/API/前端测试见 UPD-06 卡片与 `docs/evidence/UPD-06-test-cases.md`。
- 真实隔离栈验证四组各 1 位真实达人、开关、同达人双场景、重复/失败/重启和手动/采集回归。
- 未完成项、BLOCKED 项及残余风险在 UPD-06 卡片和验收报告中如实记录，不因本决策已实施而宣称生产就绪。
