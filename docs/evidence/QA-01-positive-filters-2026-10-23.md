# QA-01 正向真机补齐：粉丝量级、粉丝画像、性别/学历/黄V（2026-10-23）

> 授权：用户要求把「剩余字段也补成正向真机回归」。本轮只创建小样本任务，target=1，不扩大采集规模。
> 环境：单机 local-main；前端 127.0.0.1:5173；API 127.0.0.1:8000；执行单元 unit-local-mac-02；产品账号 media-a；系统 Chrome 156.0.8078.47。
> 契约：xingtu-ad-creator-featured-v13；能力 xingtu-ad-creator-square-v3；Adapter browser-v9。
> 方式：Playwright MCP 1.62.0-alpha over stdio + 系统 Chrome，从产品前端真实填写并提交；任务完成后用 API/PostgreSQL 交叉核对 requirement、FilterPlan、task_creators 和快照。

## 1. 结果

本轮 4 个正向任务均达到 **valid=1**，搜索成功；任务终态为 PARTIAL_COMPLETED，原因是既有 F05/F06 资料或精选完整度，不是筛选失败。

| 任务 | 正向字段 | 关键词 | 终态 | valid | 入库达人 |
|---|---|---|---|---|---|
| 2cf27cbe-2f86-4eb3-b70e-19b959874d21 | followers=10–100w | 户外 | PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE | 1 | 户外胡三浪（749,848 粉丝） |
| da2d67dd-0f1e-4fd6-a01b-33a149528af8 | fan_profile.age=24–30岁居多 | 美妆 | PARTIAL_COMPLETED / FEATURED_COLLECTION_INCOMPLETE | 1 | 仟仟QIAN（871,001 粉丝） |
| 2ff8ad00-1436-4be6-850f-c2129881849b | gender=female + education=大学生 | 大学生 | PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE | 1 | 菜就多练（102,318 粉丝） |
| 2ec9f448-4d7b-4067-863d-50ab87613925 | gender=female + yellow_v=美妆创作者 | 美妆 | PARTIAL_COMPLETED / FEATURED_COLLECTION_INCOMPLETE | 1 | 遥遥小宝（3,879,450 粉丝） |

加上此前已正向通过的地域任务 a1c874f9（湖南）、连接用户任务 f3aba74e（五维 99999）和观众画像任务 666114c3（A-12），当前已支持字段均已有至少一个正向真实任务或既有正向任务证据。

## 2. 各任务核对

### 2.1 粉丝量级

任务 2cf27cbe-2f86-4eb3-b70e-19b959874d21：
- requirement：keyword=户外，followers={min:10,max:100,unit:ten_thousand_count}；
- FilterPlan：keyword + followers.range；
- 终态 PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE，valid=1；
- 入库达人户外胡三浪粉丝 749,848，落在 10–100w；
- checkpoint 154 requests / 153 responses，failure_counts={"RESOURCE_UNAVAILABLE":2}；这是 11:55 左右一次浏览器传输/网络瞬断，Workflow 自动恢复，最终 valid=1；无 attribute filter mismatch；
- 页面任务卡显示「1 位可查看 / 失败步骤 0」。

### 2.2 粉丝画像

任务 da2d67dd-0f1e-4fd6-a01b-33a149528af8：
- requirement：keyword=美妆，fan_profile={age:["age_24_30"]}；
- FilterPlan：keyword + fan_profile.age；
- 终态 PARTIAL_COMPLETED / FEATURED_COLLECTION_INCOMPLETE，valid=1，profile=1；
- 入库达人仟仟QIAN，粉丝 871,001；
- checkpoint 78/78，failure_counts={}，无 attribute filter mismatch。

平台同条件只读探针：
- 页面已选条件：搜索词：美妆 / 粉丝画像：粉丝年龄-24-30岁居多；
- 最终请求 attribute_filter 含 {"field_name":"fans_age_rate_most","field_value":"[22]"}；
- 平台返回 316 位达人，首屏首位即仟仟QIAN。

注意：该达人快照的 audience_distributions 原始年龄分布里 18–23 占比更高（51% vs 24–30 的 25%）。本项目没有把这份通用 audience_distributions 直接当作粉丝画像的判据；平台 fans_age_rate_most=[22] 是平台自己的粉丝画像筛选项。这里记录差异，后续如需确认平台字段口径，应单独做平台侧「粉丝画像」数据对照，不应仅凭通用年龄分布判定筛选失败。

### 2.3 性别与学历

任务 2ff8ad00-1436-4be6-850f-c2129881849b：
- requirement：keyword=大学生，creator_gender=female，creator_education=undergraduate；
- FilterPlan：keyword + gender + education；
- 终态 PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE，valid=1；
- 入库达人菜就多练，粉丝 102,318；
- checkpoint 71/71，failure_counts={}，无 attribute filter mismatch。

### 2.4 性别与黄V

任务 2ec9f448-4d7b-4067-863d-50ab87613925：
- requirement：keyword=美妆，creator_gender=female，yellow_v_certification=beauty；
- FilterPlan：keyword + gender + yellow_v；
- 终态 PARTIAL_COMPLETED / FEATURED_COLLECTION_INCOMPLETE，valid=1，profile=1；
- 入库达人遥遥小宝，粉丝 3,879,450；
- checkpoint 65/65，failure_counts={}，无 attribute filter mismatch。

## 3. 平台字段值与请求映射

| 字段 | 计划值 | 平台请求值 |
|---|---|---|
| 粉丝量级 10–100w | followers.min=10、max=100 | follower__ge=100000、follower__le=1000000 |
| 粉丝画像 24–30岁居多 | age_24_30 | fans_age_rate_most=[22] |
| 性别 女性 | female | gender=2 |
| 学历 大学生 | undergraduate | persona_tag_level_one=["110213"] |
| 黄V 美妆创作者 | beauty | persona_tag_level_one=["110201"] |

前四项分别来自本轮任务/平台探针；学历、黄V 的 persona_tag_level_one 值与本轮任务 plan 一致，任务通过精确 attribute_filter 多重集关联，未出现 RESPONSE_UNCORRELATED。

## 4. 结论

- 剩余字段的正向真机覆盖已补齐：粉丝量级、粉丝画像、性别、学历、黄V 均有 valid=1 的真实任务。
- 现有证据没有显示这些字段被前端漏提交、被 P1 丢弃或被 P2 静默忽略。
- 所有任务的部分完成均来自既有 F05/F06 资料/精选完整度；搜索与筛选段没有失败步骤。
- 粉丝画像的通用 audience_distributions 与平台 fans_age_rate_most 的口径差异已记录，不能仅据此判定失败，但也不是“已经证明两个口径完全一致”。

## 5. 截图

- 粉丝量级任务：[followers-task.png](assets/qa01/round2/positive/followers-task.png)
- 粉丝量级计划：[followers-plan.png](assets/qa01/round2/positive/followers-plan.png)
- 粉丝画像任务：[fan-profile-task.png](assets/qa01/round2/positive/fan-profile-task.png)
- 粉丝画像计划：[fan-profile-plan.png](assets/qa01/round2/positive/fan-profile-plan.png)
- 性别+学历任务：[education-task.png](assets/qa01/round2/positive/education-task.png)
- 性别+学历计划：[education-plan.png](assets/qa01/round2/positive/education-plan.png)
- 性别+黄V任务：[yellow-v-task.png](assets/qa01/round2/positive/yellow-v-task.png)
- 性别+黄V计划：[yellow-v-plan.png](assets/qa01/round2/positive/yellow-v-plan.png)
