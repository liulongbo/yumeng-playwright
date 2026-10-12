import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  AlertCircle, ArrowLeft, ArrowRight, Check, ChevronRight, CircleStop, Clock3,
  ExternalLink, FileCheck2, ImageOff, ListFilter, LoaderCircle, LockKeyhole,
  PauseCircle, Play, Plus, RefreshCcw, RotateCcw, Search, ShieldCheck, Sparkles,
  UserRound, UsersRound, WandSparkles,
} from "lucide-react";
import { api, ApiError } from "./api";
import { useAuth } from "./AuthContext";
import { formatDate, shortId, statusLabel, terminalStatuses, waitingStatuses } from "./status";
import type {
  CapabilityField, ContentPage, CreatorSummary, IntakeProgress, RequirementForm, TaskDetail, TaskStatus,
} from "./types";
import { BrandMark, EmptyState, ErrorState, LoadingState, PageHeader, SkeletonRows, StatusBadge } from "./ui";

const allStatuses: TaskStatus[] = [
  "RECEIVED", "PARSING", "QUEUED", "SEARCHING", "COLLECTING", "PERSISTING",
  "RETRY_WAIT", "WAITING_FOR_LOGIN", "WAITING_FOR_ACCOUNT", "WAITING_FOR_VERIFICATION",
  "WAITING_FOR_RESOURCE", "PAUSED_BUDGET", "CANCELLING", "CANCELLED", "COMPLETED",
  "PARTIAL_COMPLETED", "FAILED_VALIDATION", "FAILED",
];

function friendlyError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "会话已失效，请重新登录";
    if (error.status === 429) return "尝试次数过多，请稍后再试";
    if (error.detail.code === "INVALID_FORM") return error.detail.message === "INVALID_CREDENTIALS" ? "账号或密码错误" : error.detail.message;
    return error.detail.message || "请求失败";
  }
  return "网络异常，请稍后重试";
}

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const destination = (location.state as { from?: string } | null)?.from || "/tasks";
  useEffect(() => { if (auth.user) navigate(destination, { replace: true }); }, [auth.user, destination, navigate]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setBusy(true);
    try { await auth.login(username, password); navigate(destination, { replace: true }); }
    catch (reason) { setError(friendlyError(reason)); }
    finally { setBusy(false); }
  }
  return <div className="login-page">
    <section className="login-story">
      <div className="story-grid" />
      <div className="story-brand"><BrandMark /><span>星采 · 媒介工作台</span></div>
      <div className="story-content">
        <span className="story-kicker"><Sparkles size={15} />让每一次筛选都有迹可循</span>
        <h1>从一个关键词，<br />抵达可用的达人名单。</h1>
        <p>需求转换、达人发现、资料采集与结果快照在同一个任务里持续推进。关闭页面，也不会中断。</p>
        <div className="story-flow"><span>筛选需求</span><i /><span>采集进度</span><i /><span>任务结果</span></div>
      </div>
      <div className="story-foot">DOUYIN XINGTU · VERIFIED CAPABILITY ONLY</div>
    </section>
    <section className="login-panel">
      <form className="login-card" onSubmit={submit}>
        <div className="mobile-brand"><BrandMark /><b>星采</b></div>
        <div className="eyebrow">SECURE ACCESS</div>
        <h2>欢迎回来</h2>
        <p>登录后查看公司共享任务与采集结果。</p>
        <label>产品账号<input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="请输入账号" required /></label>
        <label>密码<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="请输入密码" required /></label>
        {error && <div className="form-error" role="alert"><AlertCircle size={16} />{error}</div>}
        <button className="button primary login-button" disabled={busy}>{busy ? <><LoaderCircle className="spin" size={18} />正在验证</> : <>安全登录<ArrowRight size={18} /></>}</button>
        <div className="security-note"><LockKeyhole size={15} />独立产品会话 · 操作身份可审计</div>
      </form>
    </section>
  </div>;
}

export function TasksPage() {
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const params = useMemo(() => {
    const value = new URLSearchParams({ limit: "20" });
    if (status) value.set("status", status);
    if (createdFrom) value.set("created_from", new Date(`${createdFrom}T00:00:00`).toISOString());
    if (createdTo) { const exclusive = new Date(`${createdTo}T00:00:00`); exclusive.setDate(exclusive.getDate() + 1); value.set("created_to", exclusive.toISOString()); }
    if (cursor) value.set("cursor", cursor);
    return value;
  }, [status, createdFrom, createdTo, cursor]);
  const tasks = useQuery({ queryKey: ["tasks", params.toString()], queryFn: () => api.listTasks(params), refetchInterval: 15_000 });
  const visible = (tasks.data?.items ?? []).filter((task) => !keyword.trim() || (task.keyword || "").toLowerCase().includes(keyword.trim().toLowerCase()) || task.root_task_id.includes(keyword.trim()));
  const summary = tasks.data?.items.reduce((acc, task) => {
    acc.total += 1;
    if (terminalStatuses.has(task.status)) acc.terminal += 1;
    else if (waitingStatuses.has(task.status)) acc.waiting += 1;
    else acc.active += 1;
    if (["FAILED", "FAILED_VALIDATION", "PARTIAL_COMPLETED"].includes(task.status)) acc.attention += 1;
    return acc;
  }, { total: 0, active: 0, waiting: 0, terminal: 0, attention: 0 });
  return <div className="page-wrap">
    <PageHeader eyebrow="MEDIA OPERATIONS" title="任务中心" description="查看公司内所有采集任务，状态和结果以服务端记录为准。" actions={<Link to="/tasks/new" className="button primary"><Plus size={17} />创建任务</Link>} />
    <section className="metric-strip">
      <Metric label="当前列表" value={summary?.total ?? "—"} detail="按创建时间倒序" />
      <Metric label="正在推进" value={summary?.active ?? "—"} detail="转换、排队或采集中" accent="active" />
      <Metric label="等待处理" value={summary?.waiting ?? "—"} detail="资源、登录、验证或重试" accent="warning" />
      <Metric label="需要关注" value={summary?.attention ?? "—"} detail="失败或部分完成" accent="danger" />
    </section>
    <section className="panel task-panel">
      <div className="toolbar">
        <div className="search-box"><Search size={17} /><input aria-label="搜索任务" value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索关键词或任务 ID" /></div>
        <label className="select-wrap"><ListFilter size={16} /><select aria-label="按状态筛选" value={status} onChange={(e) => { setStatus(e.target.value); setCursor(null); }}><option value="">全部状态</option>{allStatuses.map((item) => <option key={item} value={item}>{statusLabel[item]}</option>)}</select></label>
        <label className="date-filter"><span>从</span><input aria-label="创建开始日期" type="date" value={createdFrom} onChange={(e) => { setCreatedFrom(e.target.value); setCursor(null); }} /></label>
        <label className="date-filter"><span>至</span><input aria-label="创建结束日期" type="date" min={createdFrom || undefined} value={createdTo} onChange={(e) => { setCreatedTo(e.target.value); setCursor(null); }} /></label>
        <button className="icon-button" title="刷新" aria-label="刷新任务" onClick={() => tasks.refetch()}><RefreshCcw size={17} className={tasks.isFetching ? "spin" : ""} /></button>
      </div>
      {tasks.isLoading ? <SkeletonRows rows={6} /> : tasks.isError ? <ErrorState error={tasks.error} retry={() => tasks.refetch()} /> : visible.length === 0 ? <EmptyState title="没有匹配的任务" description={tasks.data?.items.length ? "调整搜索词或状态筛选后再试。" : "创建第一个达人采集任务，提交后即可在这里追踪进度。"} action={!tasks.data?.items.length && <Link to="/tasks/new" className="button primary"><Plus size={16} />创建任务</Link>} /> : <div className="task-table" role="table">
        <div className="task-row table-head" role="row"><span>任务</span><span>进度</span><span>结果计数</span><span>创建信息</span><span /></div>
        {visible.map((task) => <Link className="task-row" role="row" to={`/tasks/${task.root_task_id}`} key={task.root_task_id}>
          <div className="task-main"><StatusBadge status={task.status} pulse={!terminalStatuses.has(task.status)} /><strong>{task.keyword || "系统内部任务"}</strong><span>#{shortId(task.root_task_id)} · {task.source === "product" ? "产品提交" : "内部任务"}</span></div>
          <div className="task-stage"><strong>{task.stage}</strong><div className="mini-progress"><i style={{ width: `${Math.min(100, task.counts.target_count ? task.counts.valid_count / task.counts.target_count * 100 : 0)}%` }} /></div><span>{task.counts.valid_count} / {task.counts.target_count} 位有效达人</span></div>
          <div className="count-pills"><span><b>{task.counts.discovered_count}</b>发现</span><span><b>{task.counts.profile_complete_count}</b>资料</span><span><b>{task.counts.featured_complete_count}</b>精选</span>{task.counts.failed_count > 0 && <span className="failed"><b>{task.counts.failed_count}</b>失败</span>}</div>
          <div className="task-meta"><strong>{task.created_by_name || "系统"}</strong><span>{formatDate(task.created_at)}</span></div>
          <ChevronRight size={18} />
        </Link>)}
      </div>}
      {tasks.data?.next_cursor && <div className="pagination"><button className="button secondary" onClick={() => setCursor(tasks.data!.next_cursor)}>查看更早任务<ArrowRight size={16} /></button></div>}
    </section>
  </div>;
}

function Metric({ label, value, detail, accent = "" }: { label: string; value: number | string; detail: string; accent?: string }) {
  return <div className={`metric ${accent}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function emptyRequirement(target = 20): RequirementForm {
  return { schema_version: "requirement_form.v1", platform: "douyin_xingtu", keyword: null, creator_types: [], followers: null, creator_gender: null, creator_regions: [], quote: null, sort_key: null, target_count: target };
}

export function NewTaskPage() {
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const origin = search.get("origin");
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });
  const original = useQuery({ queryKey: ["task", origin], queryFn: () => api.task(origin!), enabled: Boolean(origin) });
  const [form, setForm] = useState<RequirementForm>(emptyRequirement());
  const [clientError, setClientError] = useState("");
  const keyRef = useRef(crypto.randomUUID());
  useEffect(() => { if (capabilities.data && !origin) setForm(emptyRequirement(capabilities.data.target_count_default)); }, [capabilities.data, origin]);
  useEffect(() => { if (original.data?.requirement) setForm(original.data.requirement); }, [original.data]);
  const submit = useMutation({ mutationFn: () => api.createTask(form, keyRef.current, origin), onSuccess: (result) => navigate(`/tasks/${result.root_task_id}`) });
  function update<K extends keyof RequirementForm>(key: K, value: RequirementForm[K]) { setForm((current) => ({ ...current, [key]: value })); }
  function submitForm(event: FormEvent) {
    event.preventDefault(); setClientError("");
    if (!form.keyword?.trim() && !form.creator_types.length && !form.followers && !form.creator_gender && !form.creator_regions.length && !form.quote) { setClientError("请至少设置一项业务筛选条件。"); return; }
    submit.mutate();
  }
  if (capabilities.isLoading || (origin && original.isLoading)) return <div className="page-wrap"><LoadingState label="正在读取可用筛选能力" /></div>;
  if (capabilities.isError) return <div className="page-wrap"><ErrorState error={capabilities.error} retry={() => capabilities.refetch()} /></div>;
  const cap = capabilities.data!;
  return <div className="page-wrap narrow-page">
    <PageHeader eyebrow={origin ? "MODIFY & RESUBMIT" : "NEW COLLECTION TASK"} title={origin ? "修改并重新提交" : "创建采集任务"} description={origin ? "旧任务与原始需求保持不变，本次提交会创建一个新任务。" : "只展示当前真实核验通过的星图筛选能力。"} actions={<Link className="button ghost" to={origin ? `/tasks/${origin}` : "/tasks"}><ArrowLeft size={17} />返回</Link>} />
    <form className="intake-layout" onSubmit={submitForm}>
      <section className="panel form-panel">
        <div className="section-heading"><span className="step-index">01</span><div><h2>达人筛选条件</h2><p>系统会先转换并校验需求，合法后才申请浏览器资源。</p></div></div>
        <div className="capability-banner"><ShieldCheck size={18} /><div><strong>已核验能力版本</strong><span>{cap.capability_version}</span></div><em>{cap.fields.length} 项条件可用</em></div>
        <div className="field-grid">
          {cap.fields.map((field) => <CapabilityInput key={field.field} field={field} form={form} update={update} />)}
          <label className="field"><span>目标达人数量 <i>必填</i></span><div className="number-field"><input type="number" min={cap.target_count_min} max={cap.target_count_max} step={1} value={form.target_count} onChange={(e) => update("target_count", Number(e.target.value))} required /><b>位</b></div><small>允许 {cap.target_count_min}—{cap.target_count_max}，默认 {cap.target_count_default}。平台实际可发现数量受当前搜索能力边界限制。</small></label>
        </div>
        <div className="fixed-setting"><span>排序方式</span><strong>{cap.fixed_sort_label}</strong><small>固定由当前平台能力决定</small></div>
        {(clientError || submit.isError) && <div className="form-error" role="alert"><AlertCircle size={17} /><div><strong>{clientError || friendlyError(submit.error)}</strong>{submit.error instanceof ApiError && submit.error.detail.field_errors?.map((item) => <span key={item.path}>{item.path}：{item.message}</span>)}</div></div>}
      </section>
      <aside className="submit-card">
        <div className="section-heading compact"><span className="step-index">02</span><div><h2>确认提交</h2><p>提交后立即获得任务编号。</p></div></div>
        <dl><div><dt>平台</dt><dd>巨量星图</dd></div><div><dt>业务条件</dt><dd>{form.keyword?.trim() ? `内容关键词“${form.keyword.trim()}”` : "待填写"}</dd></div><div><dt>目标数量</dt><dd>{form.target_count} 位</dd></div><div><dt>排序</dt><dd>{cap.fixed_sort_label}</dd></div></dl>
        <div className="submit-assurance"><Check size={16} /><span>重复点击或网络重试不会创建第二个任务</span></div>
        <button className="button primary submit-button" disabled={submit.isPending}>{submit.isPending ? <><LoaderCircle className="spin" size={18} />正在可靠提交</> : <><WandSparkles size={18} />提交采集任务</>}</button>
        <p className="submit-note">提交不代表立即访问平台。需求将经过模型转换、Schema 校验和确定性业务校验。</p>
      </aside>
    </form>
  </div>;
}

function CapabilityInput({ field, form, update }: { field: CapabilityField; form: RequirementForm; update: <K extends keyof RequirementForm>(key: K, value: RequirementForm[K]) => void }) {
  if (field.field === "keyword") return <label className="field full"><span>{field.label} <i>已核验</i></span><div className="input-with-icon"><Search size={18} /><input value={form.keyword ?? ""} onChange={(e) => update("keyword", e.target.value || null)} placeholder="例如：宠物、母婴辅食、户外露营" /></div><small>按达人内容关键词查找。关键词原文不会被模型改写。</small></label>;
  if (field.field === "followers") return <div className="field full"><span>{field.label} <i>已核验</i></span><div className="range-fields"><input type="number" min="0" placeholder="最小值" onChange={(e) => update("followers", { min: e.target.value ? Number(e.target.value) : null, max: form.followers?.max ?? null, unit: "count" })} /><b>—</b><input type="number" min="0" placeholder="最大值" onChange={(e) => update("followers", { min: form.followers?.min ?? null, max: e.target.value ? Number(e.target.value) : null, unit: "count" })} /></div></div>;
  const key = field.field === "creator_type" ? "creator_types" : field.field === "region" ? "creator_regions" : field.field === "gender" ? "creator_gender" : null;
  if (key && field.options.length) return <label className="field"><span>{field.label} <i>已核验</i></span><select value={key === "creator_gender" ? form.creator_gender ?? "" : ""} onChange={(e) => { if (key === "creator_gender") update(key, e.target.value || null); else update(key, e.target.value ? [e.target.value] : []); }}><option value="">请选择</option>{field.options.map((option) => <option key={option}>{option}</option>)}</select></label>;
  return null;
}

export function TaskDetailPage() {
  const { taskId = "" } = useParams();
  const queryClient = useQueryClient();
  const commandKeys = useRef<Record<"cancel" | "continue" | "retry", string>>({ cancel: crypto.randomUUID(), continue: crypto.randomUUID(), retry: crypto.randomUUID() });
  const task = useQuery({
    queryKey: ["task", taskId], queryFn: () => api.task(taskId),
    refetchInterval: (query) => { const data = query.state.data; if (!data || terminalStatuses.has(data.status)) return false; return waitingStatuses.has(data.status) ? 15_000 : 5_000; },
  });
  const creators = useInfiniteQuery({
    queryKey: ["creators", taskId],
    queryFn: ({ pageParam }) => api.creators(taskId, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: Boolean(task.data),
  });
  useEffect(() => {
    if (task.data && terminalStatuses.has(task.data.status)) {
      queryClient.invalidateQueries({ queryKey: ["creators", taskId] });
    }
  }, [queryClient, task.data?.status, taskId]);
  const command = useMutation({
    mutationFn: (action: "cancel" | "continue" | "retry") => api.command(taskId, action, task.data!.version, commandKeys.current[action]),
    onSuccess: (detail, action) => { commandKeys.current[action] = crypto.randomUUID(); queryClient.setQueryData(["task", taskId], detail); queryClient.invalidateQueries({ queryKey: ["tasks"] }); },
    onError: (error, action) => { if (error instanceof ApiError && error.status === 409) { commandKeys.current[action] = crypto.randomUUID(); task.refetch(); } },
  });
  if (task.isLoading) return <div className="page-wrap"><LoadingState label="正在读取任务事实" /></div>;
  if (task.isError || !task.data) return <div className="page-wrap"><ErrorState error={task.error} retry={() => task.refetch()} /></div>;
  const item = task.data;
  const countCards = [
    ["已发现", item.counts.discovered_count, "候选达人"], ["有效入库", item.counts.valid_count, `目标 ${item.counts.target_count}`],
    ["资料完整", item.counts.profile_complete_count, "F05 模块"], ["精选完整", item.counts.featured_complete_count, "F06 双集合"],
  ];
  return <div className="page-wrap">
    <div className="detail-topline"><Link to="/tasks" className="back-link"><ArrowLeft size={17} />任务中心</Link><span>/</span><span>#{shortId(item.root_task_id)}</span></div>
    <PageHeader eyebrow="TASK DETAIL" title={item.keyword || "系统内部任务"} description={`任务 #${item.root_task_id}`} actions={<TaskActions task={item} busy={command.isPending} run={(action) => command.mutate(action)} />} />
    <section className="task-hero panel">
      <div className="hero-status"><StatusBadge status={item.status} pulse={!terminalStatuses.has(item.status)} /><h2>{item.stage}</h2><p>{taskMessage(item)}</p></div>
      <ProgressRail status={item.status} />
      <div className="hero-meta"><div><span>创建人</span><strong>{item.created_by_name || "系统"}</strong></div><div><span>创建时间</span><strong>{formatDate(item.created_at)}</strong></div><div><span>最近更新</span><strong>{formatDate(item.updated_at)}</strong></div><div><span>能力版本</span><strong>{item.capability_version || "历史任务"}</strong></div></div>
    </section>
    {item.challenge && <ChallengePanel task={item} />}
    {item.intake && <IntakePanel intake={item.intake} />}
    {item.failure_reason || item.field_errors.length > 0 || command.isError ? (
      <section className={attentionPanelClass(item, command.isError)}><AlertCircle size={20} /><div><strong>{attentionTitle(item)}</strong><p>{command.isError ? friendlyError(command.error) : attentionDetail(item)}</p>{item.field_errors.map((error) => <span key={`${error.path}-${error.code}`}>{error.path}：{error.message}</span>)}</div></section>
    ) : null}
    <section className="count-grid">{countCards.map(([label, value, detail]) => <div className="count-card" key={String(label)}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>)}<div className={`count-card ${item.counts.failed_count ? "danger" : ""}`}><span>失败步骤</span><strong>{item.counts.failed_count}</strong><small>可重试项由服务端判定</small></div></section>
    <div className="detail-grid">
      <section className="panel creators-panel"><div className="panel-heading"><div><h2>任务内达人</h2><p>执行中只展示已持久草稿；终态展示任务关联快照。</p></div><span>{creators.data?.pages.flatMap((page) => page.items).length ?? 0} 位可查看</span></div>
        {creators.isLoading ? <SkeletonRows rows={4} /> : creators.isError ? <ErrorState error={creators.error} retry={() => creators.refetch()} /> : !creators.data?.pages[0]?.items.length ? <EmptyState title={terminalStatuses.has(item.status) ? "当前任务没有有效达人" : "达人结果正在形成"} description={terminalStatuses.has(item.status) ? "查看任务状态与失败原因，确认是零结果、部分完成还是执行失败。" : "发现并有效落库后，达人会出现在这里。"} /> : <><div className="creator-list">{creators.data.pages.flatMap((page) => page.items).map((creator) => <CreatorRow key={creator.creator_id} taskId={taskId} creator={creator} />)}</div>{creators.hasNextPage && <div className="pagination"><button className="button secondary" disabled={creators.isFetchingNextPage} onClick={() => creators.fetchNextPage()}>{creators.isFetchingNextPage ? "正在读取" : "查看更多达人"}<ArrowRight size={16} /></button></div>}</>}
      </section>
      <aside className="panel requirement-panel"><div className="panel-heading"><div><h2>需求与执行约束</h2><p>原始需求和执行计划分开留存。</p></div></div><dl><div><dt>内容关键词</dt><dd>{item.requirement?.keyword || item.keyword || "—"}</dd></div><div><dt>目标数量</dt><dd>{item.counts.target_count} 位</dd></div><div><dt>排序方式</dt><dd>平台默认排序</dd></div><div><dt>来源</dt><dd>{item.source === "product" ? "媒介产品提交" : "系统内部任务"}</dd></div></dl>{item.plan && <details><summary>查看最终执行计划</summary><pre>{JSON.stringify(item.plan, null, 2)}</pre></details>}{item.origin_root_task_id && <Link to={`/tasks/${item.origin_root_task_id}`} className="origin-link"><RotateCcw size={15} />查看来源任务</Link>}</aside>
    </div>
  </div>;
}

function IntakePanel({ intake }: { intake: IntakeProgress }) {
  const waited = intake.pending_seconds ?? intake.blocked_seconds;
  const waitedText = typeof waited === "number" ? formatDuration(waited) : "—";
  if (!intake.blocked_reason) {
    if (intake.sent) return null;
    if (intake.consumer_alive === true) {
      return <section className="attention-panel neutral"><LoaderCircle size={20} /><div><strong>需求转换工作流正在派发</strong><p>转换工作流在线，任务会在数秒内进入需求转换阶段。</p></div></section>;
    }
    return <section className="attention-panel neutral"><Clock3 size={20} /><div><strong>等待需求转换工作流</strong><p>任务已可靠保存，正在等待转换工作流派发（已等待 {waitedText}）。</p></div></section>;
  }
  const messages: Record<string, { title: string; detail: string }> = {
    INTAKE_WORKER_UNAVAILABLE: {
      title: "需求转换工作流未运行",
      detail: `任务不会被自动推进：没有检测到需求转换（Intake）Worker 的在线消费者，已等待 ${waitedText}。请在运行环境启动需求转换工作流。`,
    },
    INTAKE_DISPATCH_FAILING: {
      title: "需求派发失败",
      detail: `转换工作流尝试派发该任务但失败${intake.dispatch_error ? `（${intake.dispatch_error}）` : ""}，已等待 ${waitedText}。系统会自动重试，请同时检查消息队列与工作流服务。`,
    },
  };
  const message = messages[intake.blocked_reason] || {
    title: "需求转换未推进",
    detail: `服务端报告阻塞原因 ${intake.blocked_reason}，已等待 ${waitedText}。`,
  };
  return <section className="attention-panel"><AlertCircle size={20} /><div><strong>{message.title}</strong><p>{message.detail}</p><span>任务编号可在任务中心检索；此状态不代表需求内容有误。</span></div></section>;
}

// A user-initiated cancellation is a completed command, not a failure: it must not appear as a red
// "needs attention" panel, and no internal failure code may be shown as the reason.
const CANCELLED_REASONS = new Set(["TASK_CANCELLED"]);
// The only non-cancellation reason whose user-facing wording is a fixed promise about the offered
// action; everything else keeps the server-provided reason verbatim.
const RETRYABLE_REASONS = new Map([
  ["PROFILE_SCOPE_INCOMPLETE", "有位达人的主页资料本次未能全部读到（已成功读取的部分和精选作品已经保存）。请点「重试失败步骤」补齐该达人；重试只补采缺失模块，不会重复创建任务。"],
]);

function isUserCancelled(task: TaskDetail) {
  return task.status === "CANCELLED" || (task.failure_reason ? CANCELLED_REASONS.has(task.failure_reason) : false);
}

function attentionPanelClass(task: TaskDetail, commandFailed: boolean) {
  if (!commandFailed && isUserCancelled(task) && !task.field_errors.length) return "attention-panel neutral";
  return "attention-panel";
}

function attentionTitle(task: TaskDetail) {
  if (task.status === "FAILED_VALIDATION") return "需求未通过确定性校验";
  if (isUserCancelled(task)) return "任务已取消";
  return "任务需要关注";
}

function attentionDetail(task: TaskDetail) {
  if (isUserCancelled(task)) return "任务已按你的操作取消，已持久的结果会保留。";
  // A transient platform response can leave one profile module incomplete while everything else —
  // including the persisted results — is fine. Say what happened and that the offered action is
  // real instead of showing a bare internal code (FIX-01 P0-A acceptance wording).
  const retryable = task.failure_reason ? RETRYABLE_REASONS.get(task.failure_reason) : undefined;
  if (retryable) return retryable;
  return task.failure_reason || "请根据字段提示修改后重新提交。";
}

function taskMessage(task: TaskDetail) {
  const messages: Partial<Record<TaskStatus, string>> = {
    RECEIVED: "需求已可靠保存，等待转换工作流接管。", PARSING: "正在把原始筛选条件转换为可执行计划，并逐字段校验。",
    QUEUED: "执行计划已通过校验，正在等待采集资源。", SEARCHING: "正在星图中按已核验条件发现达人。",
    COLLECTING: "正在采集达人主页资料与两组精选作品。", PERSISTING: "数据已采集，正在发布任务不可变快照。",
    COMPLETED: "目标链路已完成，可查看发布快照。", PARTIAL_COMPLETED: "部分结果已保存，请查看失败步骤与可用操作。",
    FAILED_VALIDATION: "原始需求未能安全映射为执行计划，未申请浏览器资源。", FAILED: "执行未完成，已保存的结果不会丢失。",
    CANCELLING: "取消已受理，正在等待执行中的步骤安全收尾。", CANCELLED: "任务已按你的操作取消，已持久的结果保留。",
    PAUSED_BUDGET: "本次执行预算已用完，可在确认后继续。", WAITING_FOR_LOGIN: "平台会话需要维护，本里程碑暂不提供远程登录入口。",
    WAITING_FOR_ACCOUNT: "当前平台账号与任务绑定账号不一致，采集已暂停。",
    WAITING_FOR_VERIFICATION: "平台要求安全验证，业务采集已暂停，完成验证并稳定后会自动恢复。",
  };
  if (task.status === "RECEIVED" && task.intake) {
    if (task.intake.blocked_reason) return "需求已保存，但转换工作流没有推进该任务；请查看下方阻塞说明。";
    if (task.intake.sent) return "需求已派发，转换工作流正在接管。";
  }
  return messages[task.status] || "任务状态已从服务端恢复，页面会按需自动更新。";
}

function formatDuration(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}小时${minutes % 60}分`;
  if (minutes > 0) return `${minutes}分${String(rest).padStart(2, "0")}秒`;
  return `${rest}秒`;
}

function ChallengePanel({ task }: { task: TaskDetail }) {
  const challenge = task.challenge!;
  const stateLabel: Record<string, string> = {
    DETECTED: "已检测", HANDLING: "等待处理", VERIFIED: "已恢复",
    TIMEOUT: "已超时", FAILED: "恢复失败", LIMIT_EXCEEDED: "达到上限",
  };
  return <section className={`challenge-panel ${challenge.terminal_reason ? "terminal" : ""}`}>
    <div className="challenge-icon"><ShieldCheck size={20} /></div>
    <div className="challenge-copy">
      <div className="challenge-heading"><strong>安全验证托管</strong><span>{stateLabel[challenge.state] || challenge.state}</span></div>
      <p>{challenge.terminal_message || (challenge.requires_user_action ? "请在平台原生页面完成安全验证；系统不会操作验证控件。" : "验证状态已记录，后续恢复由服务端检查决定。")}</p>
      <div className="challenge-facts">
        <span><b>{challenge.detected_count}</b>触发次数</span>
        <span><b>{challenge.recovery_count}</b>恢复次数</span>
        <span><b>{formatDuration(challenge.waiting_seconds)}</b>当前等待</span>
        <span><b>{challenge.remaining_creator_count}</b>剩余达人</span>
      </div>
      <div className="challenge-foot">
        {challenge.current_creator_id && <span>当前达人 {challenge.current_creator_id}</span>}
        <span>{challenge.monitoring ? "正在监测稳定恢复条件" : "未处于实时监测"}</span>
        <span>{challenge.delivered_result}</span>
      </div>
    </div>
  </section>;
}

function TaskActions({ task, busy, run }: { task: TaskDetail; busy: boolean; run: (action: "cancel" | "continue" | "retry") => void }) {
  return <div className="task-actions">
    {task.allowed_actions.includes("modify_resubmit") && <Link to={`/tasks/new?origin=${task.root_task_id}`} className="button secondary"><RotateCcw size={16} />修改重提</Link>}
    {task.allowed_actions.includes("continue") && <button className="button primary" disabled={busy} onClick={() => run("continue")}><Play size={16} />继续任务</button>}
    {task.allowed_actions.includes("retry") && <button className="button primary" disabled={busy} onClick={() => run("retry")}><RefreshCcw size={16} />重试失败步骤</button>}
    {task.allowed_actions.includes("cancel") && <button className="button danger-button" disabled={busy} onClick={() => window.confirm("确认取消这个任务？已持久的结果会保留。") && run("cancel")}><CircleStop size={16} />取消任务</button>}
  </div>;
}

function ProgressRail({ status }: { status: TaskStatus }) {
  const stages = [{ label: "需求接收", states: ["RECEIVED"] }, { label: "转换校验", states: ["PARSING", "FAILED_VALIDATION"] }, { label: "排队", states: ["QUEUED", "WAITING_FOR_RESOURCE"] }, { label: "发现达人", states: ["SEARCHING"] }, { label: "采集资料", states: ["COLLECTING", "RETRY_WAIT", "WAITING_FOR_LOGIN", "WAITING_FOR_ACCOUNT", "WAITING_FOR_VERIFICATION", "PAUSED_BUDGET"] }, { label: "发布结果", states: ["PERSISTING", "COMPLETED", "PARTIAL_COMPLETED"] }];
  const current = Math.max(0, stages.findIndex((stage) => stage.states.includes(status)));
  return <div className="progress-rail">{stages.map((stage, index) => <div className={`${index < current ? "done" : index === current ? "current" : ""}`} key={stage.label}><span>{index < current ? <Check size={14} /> : index + 1}</span><b>{stage.label}</b></div>)}</div>;
}

function getText(payload: Record<string, unknown>, keys: string[]): string | null {
  const queue: unknown[] = [payload]; let inspected = 0;
  while (queue.length && inspected < 200) { const value = queue.shift(); inspected += 1; if (!value || typeof value !== "object") continue; for (const [key, child] of Object.entries(value)) { if (keys.includes(key) && ["string", "number"].includes(typeof child)) return String(child); if (child && typeof child === "object") queue.push(child); } }
  return null;
}

function CreatorRow({ taskId, creator }: { taskId: string; creator: CreatorSummary }) {
  const name = getText(creator.payload, ["nickname", "name", "display_name"]) || `达人 ${creator.first_position + 1}`;
  const followers = getText(creator.payload, ["follower_count", "followers", "fans_count"]);
  return <Link className="creator-row" to={`/tasks/${taskId}/creators/${creator.creator_id}`}><div className="creator-rank">{String(creator.first_position + 1).padStart(2, "0")}</div><div className="creator-avatar"><UserRound size={20} /></div><div className="creator-copy"><strong>{name}</strong><span>平台 ID {creator.platform_creator_id}</span></div>{followers && <div className="creator-stat"><span>粉丝</span><strong>{followers}</strong></div>}<span className={`view-label ${creator.view_kind}`}>{creator.view_kind === "draft" ? "执行中草稿" : "已发布快照"}</span><ChevronRight size={18} /></Link>;
}

export function CreatorDetailPage() {
  const { taskId = "", creatorId = "" } = useParams();
  const [tab, setTab] = useState<"excellent_reach" | "excellent_seeding">("excellent_reach");
  const creator = useQuery({ queryKey: ["creator", taskId, creatorId], queryFn: () => api.creator(taskId, creatorId) });
  const contents = useInfiniteQuery({ queryKey: ["contents", taskId, creatorId, tab], queryFn: ({ pageParam }) => api.contents(taskId, creatorId, tab, pageParam), initialPageParam: null as string | null, getNextPageParam: (page) => page.next_cursor ?? undefined, enabled: Boolean(creator.data) });
  if (creator.isLoading) return <div className="page-wrap"><LoadingState label="正在读取达人快照" /></div>;
  if (creator.isError || !creator.data) return <div className="page-wrap"><ErrorState error={creator.error} retry={() => creator.refetch()} /></div>;
  const item = creator.data; const name = getText(item.payload, ["nickname", "name", "display_name"]) || `达人 ${item.first_position + 1}`;
  return <div className="page-wrap">
    <div className="detail-topline"><Link to={`/tasks/${taskId}`} className="back-link"><ArrowLeft size={17} />返回任务</Link><span>/</span><span>{name}</span></div>
    <PageHeader eyebrow="CREATOR SNAPSHOT" title={name} description={`平台 ID ${item.platform_creator_id}`} actions={<span className={`view-label large ${item.view_kind}`}>{item.view_kind === "draft" ? "执行中草稿" : "不可变任务快照"}</span>} />
    {item.view_kind === "draft" && <div className="draft-banner"><Clock3 size={18} /><div><strong>这是执行中的持久草稿</strong><span>字段与作品仍可能补齐；任务发布后将切换到不可变快照。</span></div></div>}
    <div className="creator-detail-grid">
      <section className="panel profile-panel"><div className="panel-heading"><div><h2>达人资料模块</h2><p>{item.observed_at ? `观测于 ${formatDate(item.observed_at)}` : "仅展示已持久数据"}</p></div><FileCheck2 size={20} /></div><ProfileModules payload={item.payload} /></section>
      <section className="panel content-panel"><div className="panel-heading"><div><h2>精选作品</h2><p>两组集合独立呈现，跨组重复作品保留。</p></div></div><div className="tabs" role="tablist"><button role="tab" aria-selected={tab === "excellent_reach"} className={tab === "excellent_reach" ? "active" : ""} onClick={() => setTab("excellent_reach")}>优秀传播视频</button><button role="tab" aria-selected={tab === "excellent_seeding"} className={tab === "excellent_seeding" ? "active" : ""} onClick={() => setTab("excellent_seeding")}>优秀种草视频</button></div>{contents.isLoading ? <SkeletonRows rows={3} /> : contents.isError ? <ErrorState error={contents.error} retry={() => contents.refetch()} /> : <><ContentCards page={{ ...contents.data!.pages[0], cards: contents.data!.pages.flatMap((page) => page.cards) }} taskId={taskId} />{contents.hasNextPage && <div className="pagination"><button className="button secondary" disabled={contents.isFetchingNextPage} onClick={() => contents.fetchNextPage()}>{contents.isFetchingNextPage ? "正在读取" : "查看更多作品"}<ArrowRight size={16} /></button></div>}</>}</section>
    </div>
  </div>;
}

function ProfileModules({ payload }: { payload: Record<string, unknown> }) {
  const raw = payload.modules;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    const entries = Object.entries(payload).filter(([, value]) => ["string", "number", "boolean"].includes(typeof value)).slice(0, 12);
    if (!entries.length) return <EmptyState title="资料模块尚未形成" description="执行中只展示已持久字段，不使用空值替代失败或未采集状态。" />;
    return <div className="field-list">{entries.map(([key, value]) => <div key={key}><span>{key}</span><strong>{String(value)}</strong></div>)}</div>;
  }
  return <div className="module-list">{Object.entries(raw as Record<string, unknown>).map(([key, value]) => <details key={key} open><summary><span>{key}</span><em>{moduleState(value)}</em></summary><ModuleFields value={value} /></details>)}</div>;
}

function moduleState(value: unknown) { if (value && typeof value === "object" && "status" in value) return String((value as Record<string, unknown>).status); return "已记录"; }
function ModuleFields({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <p className="muted">{String(value ?? "未提供")}</p>;
  const record = value as Record<string, unknown>; const fields = Array.isArray(record.fields) ? record.fields : Object.entries(record).filter(([key]) => !["status", "failure_reason", "complete"].includes(key)).map(([field_key, fieldValue]) => ({ field_key, value: fieldValue }));
  if (!fields.length) return <p className="muted">{String(record.failure_reason || "当前模块没有可展示字段")}</p>;
  return <div className="field-list">{fields.slice(0, 30).map((raw, index) => { const field = raw as Record<string, unknown>; return <div key={String(field.field_key || index)}><span>{String(field.field_key || field.key || `字段 ${index + 1}`)}{Boolean(field.status) && <i className={`field-status ${String(field.status).toLowerCase()}`}>{String(field.status)}</i>}</span><strong>{displayValue(field.value ?? field.normalized_value ?? field)}</strong></div>; })}</div>;
}
function displayValue(value: unknown) { if (value === null || value === undefined || value === "") return "—"; if (typeof value === "object") return JSON.stringify(value); return String(value); }

function ContentCards({ page, taskId }: { page: ContentPage; taskId: string }) {
  if (!page.cards.length) return <EmptyState title="该集合暂无作品" description={page.status === "COMPLETE" ? "平台已确认该集合为空。" : `当前集合状态：${page.status}`} />;
  return <div className="content-cards">{page.cards.map((outer, index) => { const payload = ((outer.payload && typeof outer.payload === "object") ? outer.payload : outer) as Record<string, unknown>; const cover = (payload.cover && typeof payload.cover === "object" ? payload.cover : {}) as Record<string, unknown>; const objectId = String(cover.object_id || outer.cover_object_id || ""); const link = String(payload.canonical_link || payload.share_url || ""); const title = String(payload.title || payload.description || `精选作品 ${index + 1}`); const coverStatus = String(outer.cover_status || cover.status || "NOT_ATTEMPTED"); return <article className="content-card" key={String(outer.card_id || payload.card_id || index)}><div className="cover-box">{objectId && coverStatus === "STORED" ? <img src={`/api/tasks/${taskId}/covers/${encodeURIComponent(objectId)}`} alt="" /> : <div className="cover-missing"><ImageOff size={20} /><span>{coverStatus === "FAILED" ? "封面失败" : "暂无封面"}</span></div>}<span>{String(Number(outer.position ?? payload.position ?? index) + 1).padStart(2, "0")}</span></div><div className="content-copy"><strong>{title}</strong><p>{String(payload.platform_content_id || "平台作品")}</p><div className="content-meta"><span>{page.view_kind === "draft" ? "草稿" : "快照"}</span>{Array.isArray(outer.truncated_fields) && outer.truncated_fields.length > 0 && <span>部分字段截断</span>}</div></div>{link && link !== "null" ? <a href={link} target="_blank" rel="noreferrer" aria-label="打开平台作品"><ExternalLink size={17} /></a> : <span className="no-link">无链接</span>}</article>; })}</div>;
}
