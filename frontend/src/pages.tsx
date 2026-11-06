import { useEffect, useMemo, useRef, useState, type Dispatch, type FormEvent, type ReactNode, type SetStateAction } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  AlertCircle, ArrowLeft, ArrowRight, Check, ChevronRight, CircleStop, Clock3,
  ExternalLink, Eye, EyeOff, FileCheck2, ImageOff, ListFilter, LoaderCircle, LockKeyhole,
  Play, Plus, RefreshCcw, RotateCcw, Search, ShieldCheck, Sparkles,
  UserRound, UsersRound, WandSparkles, MonitorCog, MousePointer2, TriangleAlert, X,
} from "lucide-react";
import { api, ApiError } from "./api";
import { useAuth } from "./AuthContext";
import { snapshotCreatorView } from "./snapshotCreator";
import { CreatorProfile } from "./profile/CreatorProfile";
import { QuoteTable } from "./profile/panels";
import type { FeaturedCardView, FeaturedCollectionView, FeaturedContent } from "./profile/commercial";
import { ProvenanceDrawer } from "./profile/audience";
import { indexCatalog, useFieldCatalog } from "./fieldCatalog";
import { LiveCreatorDetailView, liveMetricList, payloadDisplayName } from "./liveCreator";
import { EMPTY_LIVE_FILTERS, LiveFilterFields, liveFilterSummary, validateLiveFilters } from "./liveFilters";
import { formatDate, shortId, statusLabel, terminalStatuses, waitingStatuses } from "./status";
import type {
  AudienceProfile, CapabilityDimension, CapabilityField, ContentPage,
  CreatorLibraryDetail, CreatorLibraryQuote, CreatorLibrarySummary, CreatorSummary, CreatorScene,
  CreatorVideoPage, LiveMetricEnvelope, LiveRequirementForm,
  CountRangeValue, IntakeProgress, BrowserTakeover, ExecutionUnit, RangeValue, RequirementForm,
  RequirementFormV1, RequirementFormV2, RequirementFormV3, TaskDetail, TaskKind, TaskStatus,
} from "./types";
import { BrandMark, EmptyState, ErrorState, LoadingState, PageHeader, SkeletonRows, StatusBadge } from "./ui";

const taskKindLabel: Record<TaskKind, string> = {
  collection: "采集任务",
  manual_update: "手动更新",
  scheduled_update: "定时更新",
};
const platformLabel = { douyin_xingtu: "巨量星图", kuaishou_juxing: "磁力聚星" } as const;

function taskTitle(task: { task_kind?: TaskKind; keyword: string | null; creator_scene?: CreatorScene; counts: { target_count: number } }) {
  if (!task.task_kind || task.task_kind === "collection") {
    if (task.keyword) return task.keyword;
    return task.creator_scene === "live_square" ? "直播广场筛选采集" : "系统内部任务";
  }
  return `${taskKindLabel[task.task_kind]} · ${task.counts.target_count} 位达人`;
}

const updateTargetStateLabel: Record<string, string> = {
  pending: "等待更新",
  collecting: "更新中",
  done: "已完成",
  invalid: "达人无效",
  failed: "失败",
};

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
  const [passwordVisible, setPasswordVisible] = useState(false);
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
        <label>密码
          {/* 默认保持隐藏；切换只改 input 的 type，受控 value 不参与，因此已输入内容不会被清空。 */}
          <div className="password-field">
            <input type={passwordVisible ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="请输入密码" required />
            <button type="button" className="password-toggle" aria-label={passwordVisible ? "隐藏密码" : "显示密码"} aria-pressed={passwordVisible} title={passwordVisible ? "隐藏密码" : "显示密码"} onClick={() => setPasswordVisible((visible) => !visible)}>
              {passwordVisible ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
          </div>
        </label>
        {error && <div className="form-error" role="alert"><AlertCircle size={16} />{error}</div>}
        <button className="button primary login-button" disabled={busy}>{busy ? <><LoaderCircle className="spin" size={18} />正在验证</> : <>安全登录<ArrowRight size={18} /></>}</button>
        <div className="security-note"><LockKeyhole size={15} />独立产品会话 · 操作身份可审计</div>
      </form>
    </section>
  </div>;
}

export function TasksPage() {
  const [status, setStatus] = useState("");
  const [taskKind, setTaskKind] = useState("");
  const [platform, setPlatform] = useState("");
  const [scene, setScene] = useState("");
  const [keyword, setKeyword] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const params = useMemo(() => {
    const value = new URLSearchParams({ limit: "20" });
    if (status) value.set("status", status);
    if (taskKind) value.set("task_kind", taskKind);
    if (platform) value.set("platform", platform);
    if (scene) value.set("creator_scene", scene);
    if (createdFrom) value.set("created_from", new Date(`${createdFrom}T00:00:00`).toISOString());
    if (createdTo) { const exclusive = new Date(`${createdTo}T00:00:00`); exclusive.setDate(exclusive.getDate() + 1); value.set("created_to", exclusive.toISOString()); }
    if (cursor) value.set("cursor", cursor);
    return value;
  }, [status, taskKind, platform, scene, createdFrom, createdTo, cursor]);
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
        <label className="select-wrap"><ListFilter size={16} /><select aria-label="按平台筛选" value={platform} onChange={(e) => { setPlatform(e.target.value); setCursor(null); }}><option value="">全部平台</option><option value="douyin_xingtu">巨量星图</option><option value="kuaishou_juxing">磁力聚星</option></select></label>
        <label className="select-wrap"><ListFilter size={16} /><select aria-label="按场景筛选" value={scene} onChange={(e) => { setScene(e.target.value); setCursor(null); }}><option value="">全部场景</option><option value="video_square">短视频广场</option><option value="live_square">直播广场</option></select></label>
        <label className="select-wrap"><ListFilter size={16} /><select aria-label="按任务类型筛选" value={taskKind} onChange={(e) => { setTaskKind(e.target.value); setCursor(null); }}><option value="">全部类型</option><option value="collection">采集任务</option><option value="manual_update">手动更新</option><option value="scheduled_update">定时更新</option></select></label>
        <label className="select-wrap"><ListFilter size={16} /><select aria-label="按状态筛选" value={status} onChange={(e) => { setStatus(e.target.value); setCursor(null); }}><option value="">全部状态</option>{allStatuses.map((item) => <option key={item} value={item}>{statusLabel[item]}</option>)}</select></label>
        <label className="date-filter"><span>从</span><input aria-label="创建开始日期" type="date" value={createdFrom} onChange={(e) => { setCreatedFrom(e.target.value); setCursor(null); }} /></label>
        <label className="date-filter"><span>至</span><input aria-label="创建结束日期" type="date" min={createdFrom || undefined} value={createdTo} onChange={(e) => { setCreatedTo(e.target.value); setCursor(null); }} /></label>
        <button className="icon-button" title="刷新" aria-label="刷新任务" onClick={() => tasks.refetch()}><RefreshCcw size={17} className={tasks.isFetching ? "spin" : ""} /></button>
      </div>
      {tasks.isLoading ? <SkeletonRows rows={6} /> : tasks.isError ? <ErrorState error={tasks.error} retry={() => tasks.refetch()} /> : visible.length === 0 ? <EmptyState title="没有匹配的任务" description={tasks.data?.items.length ? "调整搜索词或状态筛选后再试。" : "创建第一个达人采集任务，提交后即可在这里追踪进度。"} action={!tasks.data?.items.length && <Link to="/tasks/new" className="button primary"><Plus size={16} />创建任务</Link>} /> : <div className="task-table" role="table">
        <div className="task-row table-head" role="row"><span>任务</span><span>进度</span><span>结果计数</span><span>创建信息</span><span /></div>
        {visible.map((task) => <Link className="task-row" role="row" to={`/tasks/${task.root_task_id}`} key={task.root_task_id}>
          <div className="task-main"><StatusBadge status={task.status} pulse={!terminalStatuses.has(task.status)} /><strong>{taskTitle(task)}</strong><span>#{shortId(task.root_task_id)} · {platformLabel[task.platform ?? "douyin_xingtu"]} · {task.creator_scene === "live_square" ? "直播广场" : "短视频广场"} · {taskKindLabel[task.task_kind] || taskKindLabel.collection} · {task.source === "product" ? "产品提交" : "内部任务"}</span>{task.failure_reason === "ACCOUNT_SELECTION_REQUIRED" && <span className="task-account-alert">需要选择子账号</span>}</div>
          <div className="task-stage"><strong>{task.stage}</strong><div className="mini-progress"><i style={{ width: `${Math.min(100, task.counts.target_count ? task.counts.valid_count / task.counts.target_count * 100 : 0)}%` }} /></div><span>{task.counts.valid_count} / {task.counts.target_count} 位{(task.task_kind ?? "collection") === "collection" ? "有效达人" : "已更新"}</span></div>
          <div className="count-pills"><span><b>{task.counts.discovered_count}</b>{(task.task_kind ?? "collection") === "collection" ? "发现" : "目标"}</span><span><b>{task.counts.profile_complete_count}</b>资料</span>{task.platform !== "kuaishou_juxing" && task.creator_scene !== "live_square" && <span><b>{task.counts.featured_complete_count}</b>精选</span>}{task.counts.failed_count > 0 && <span className="failed"><b>{task.counts.failed_count}</b>失败</span>}</div>
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

function emptyRequirement(target = 20): RequirementFormV2 {
  return { schema_version: "requirement_form.v2", platform: "douyin_xingtu", keyword: null, creator_types: [], followers: null, creator_gender: null, creator_regions: [], creator_education: null, yellow_v_certification: null, connection_users: null, viewer_profile: null, fan_profile: null, quote: null, sort_key: null, target_count: target };
}

function emptyJuxingRequirement(target = 10): RequirementFormV3 {
  return {
    schema_version: "requirement_form.v3", platform: "kuaishou_juxing", keyword: null,
    content_types: [], creator_types: [], followers: null, creator_gender: null,
    creator_regions: [], creator_education: null, yellow_v_certification: null,
    connection_users: null, viewer_profile: null, fan_profile: null, quote: null,
    juxing_video_quotes: null, sort_key: null, target_count: target,
  };
}

function emptyLive(platform: "douyin_xingtu" | "kuaishou_juxing", target = 20): LiveRequirementForm {
  return {
    schema_version: platform === "kuaishou_juxing" ? "requirement_form.v3" : "requirement_form.v2",
    platform,
    creator_scene: "live_square",
    keyword: null,
    live_filters: EMPTY_LIVE_FILTERS,
    target_count: target,
  };
}

function upgradeRequirement(form: RequirementFormV1 | RequirementFormV2 | RequirementFormV3): RequirementFormV2 {
  if (form.schema_version === "requirement_form.v2") return form;
  const upgraded = emptyRequirement(form.target_count);
  upgraded.keyword = form.keyword;
  if (form.creator_gender === "male" || form.creator_gender === "female") upgraded.creator_gender = form.creator_gender;
  if (form.followers) upgraded.followers = { min: form.followers.min === null ? null : form.followers.min / 10_000, max: form.followers.max === null ? null : form.followers.max / 10_000, unit: "ten_thousand_count" };
  upgraded.sort_key = form.sort_key;
  return upgraded;
}

function emptyProfile(): AudienceProfile {
  return { age: [], gender: null, device_brand: [], city_level: [], crowd: [] };
}

function hasBusinessFilter(form: RequirementFormV2) {
  return Boolean(form.keyword?.trim() || form.creator_gender || form.creator_regions.length || form.creator_education || form.yellow_v_certification || form.connection_users || form.followers || form.viewer_profile || form.fan_profile);
}

export function NewTaskPage() {
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const origin = search.get("origin");
  const [selectedPlatform, setSelectedPlatform] = useState<"douyin_xingtu" | "kuaishou_juxing">("douyin_xingtu");
  const [selectedScene, setSelectedScene] = useState<CreatorScene>("video_square");
  const capabilities = useQuery({
    queryKey: ["capabilities", selectedPlatform, selectedScene],
    queryFn: () => api.capabilities(selectedPlatform, selectedScene),
  });
  const platforms = useQuery({ queryKey: ["platforms"], queryFn: api.platforms, retry: false });
  const original = useQuery({ queryKey: ["task", origin], queryFn: () => api.task(origin!), enabled: Boolean(origin) });
  const [form, setForm] = useState<RequirementFormV2>(emptyRequirement());
  const [juxingForm, setJuxingForm] = useState<RequirementFormV3>(emptyJuxingRequirement());
  const [liveForm, setLiveForm] = useState<LiveRequirementForm>(emptyLive("douyin_xingtu"));
  const [clientError, setClientError] = useState("");
  const keyRef = useRef(crypto.randomUUID());
  useEffect(() => {
    if (!capabilities.data || origin) return;
    if (selectedScene === "live_square") {
      setLiveForm(emptyLive(selectedPlatform, Math.min(capabilities.data.target_count_default, capabilities.data.target_count_max)));
      return;
    }
    if (selectedPlatform === "douyin_xingtu") setForm(emptyRequirement(capabilities.data.target_count_default));
    else setJuxingForm(emptyJuxingRequirement(capabilities.data.target_count_default));
  }, [capabilities.data, origin, selectedPlatform, selectedScene]);
  useEffect(() => {
    const requirement = original.data?.requirement;
    if (!requirement) return;
    const scene = (requirement as { creator_scene?: CreatorScene }).creator_scene;
    if (scene === "live_square") {
      setSelectedScene("live_square");
      const platform = requirement.platform;
      setSelectedPlatform(platform);
      setLiveForm({
        schema_version: platform === "kuaishou_juxing" ? "requirement_form.v3" : "requirement_form.v2",
        platform,
        creator_scene: "live_square",
        keyword: ("keyword" in requirement ? requirement.keyword : null) ?? null,
        live_filters: ("live_filters" in requirement ? (requirement as LiveRequirementForm).live_filters : []) ?? [],
        target_count: requirement.target_count,
      });
      return;
    }
    setSelectedScene("video_square");
    if (requirement.schema_version === "requirement_form.v3") {
      setSelectedPlatform("kuaishou_juxing"); setJuxingForm(requirement as RequirementFormV3);
    } else { setSelectedPlatform("douyin_xingtu"); setForm(upgradeRequirement(requirement as RequirementFormV1 | RequirementFormV2 | RequirementFormV3)); }
  }, [original.data]);
  const activeForm: RequirementForm = selectedScene === "live_square"
    ? liveForm
    : selectedPlatform === "douyin_xingtu" ? form : juxingForm;
  const submit = useMutation({ mutationFn: () => api.createTask(activeForm, keyRef.current, origin), onSuccess: (result) => navigate(`/tasks/${result.root_task_id}`) });
  function update<K extends keyof RequirementFormV2>(key: K, value: RequirementFormV2[K]) { setForm((current) => ({ ...current, [key]: value })); }
  function submitForm(event: FormEvent) {
    event.preventDefault(); setClientError("");
    if (selectedScene === "live_square") {
      const liveCapability = capabilities.data;
      if (!liveCapability) return;
      const liveError = validateLiveFilters(
        liveForm,
        liveCapability.fields,
        liveCapability.combination_policy,
      );
      if (liveError) { setClientError(liveError); return; }
      submit.mutate();
      return;
    }
    const hasFilter = selectedPlatform === "douyin_xingtu"
      ? hasBusinessFilter(form)
      : Boolean(juxingForm.keyword?.trim() || juxingForm.content_types.length || juxingForm.followers || juxingForm.creator_regions.length || juxingForm.juxing_video_quotes);
    if (!hasFilter) { setClientError("请至少设置一项业务筛选条件。"); return; }
    submit.mutate();
  }
  if (capabilities.isLoading || (origin && original.isLoading)) return <div className="page-wrap"><LoadingState label="正在读取可用筛选能力" /></div>;
  if (capabilities.isError) return <div className="page-wrap"><ErrorState error={capabilities.error} retry={() => capabilities.refetch()} /></div>;
  const cap = capabilities.data!;
  const keywordField = cap.fields.find((field) => field.field === "keyword");
  const backgroundFields = cap.fields.filter((field) => field.group === "背景信息");
  const audienceFields = cap.fields.filter((field) => field.group === "受众画像");
  const sceneOptions = platforms.data?.find((option) => option.platform === selectedPlatform)?.scenes ?? [
    { scene: "video_square" as const, label: "短视频广场", enabled: true, capability_status: "verified" as const, contract_version: cap.capability_version },
    { scene: "live_square" as const, label: "直播广场", enabled: false, capability_status: "unavailable" as const, contract_version: null, disabled_reason: "直播能力尚未启用" },
  ];
  const sceneLabel = sceneOptions.find((option) => option.scene === selectedScene)?.label || (selectedScene === "live_square" ? "直播广场" : "短视频广场");
  const summary = selectedScene === "live_square"
    ? liveFilterSummary(liveForm, cap.fields)
    : selectedPlatform === "douyin_xingtu"
      ? selectedConditionSummary(form, cap.fields)
      : selectedJuxingConditionSummary(juxingForm, cap.fields);
  return <div className="page-wrap narrow-page">
    <PageHeader eyebrow={origin ? "MODIFY & RESUBMIT" : "NEW COLLECTION TASK"} title={origin ? "修改并重新提交" : "创建采集任务"} description={origin ? "旧任务与原始需求保持不变，本次提交会创建一个新任务。" : "按所选平台仅展示当前真实核验通过的筛选能力。"} actions={<Link className="button ghost" to={origin ? `/tasks/${origin}` : "/tasks"}><ArrowLeft size={17} />返回</Link>} />
    <form className="intake-layout" onSubmit={submitForm}>
      <section className="panel form-panel">
        <div className="section-heading"><span className="step-index">00</span><div><h2>采集平台</h2><p>一个任务只访问一个平台；不同平台不会在同一任务内同时启动。</p></div></div>
        <div className="platform-selector" role="radiogroup" aria-label="采集平台">
          {(platforms.data ?? [
            { platform: "douyin_xingtu", label: "巨量星图", enabled: true, capability_status: "verified", contract_version: cap.capability_version },
            { platform: "kuaishou_juxing", label: "磁力聚星", enabled: false, capability_status: "observed", contract_version: null, disabled_reason: "等待授权环境完成筛选回读与真实合同验证" },
          ]).map((platform) => <button key={platform.platform} type="button" role="radio" aria-checked={platform.platform === selectedPlatform} className={`platform-option ${platform.platform === selectedPlatform ? "active" : ""}`} disabled={!platform.enabled} onClick={() => { setSelectedPlatform(platform.platform); setSelectedScene("video_square"); setClientError(""); keyRef.current = crypto.randomUUID(); }}><strong>{platform.label}</strong><span>{platform.capability_status === "verified" ? "已验证可用" : "能力已观察，尚待验证"}</span>{platform.disabled_reason && <small>{platform.disabled_reason}</small>}</button>)}
        </div>
        <div className="platform-selector" role="radiogroup" aria-label="采集场景">
          {sceneOptions.map((scene) => <button key={scene.scene} type="button" role="radio" aria-checked={scene.scene === selectedScene} className={`platform-option ${scene.scene === selectedScene ? "active" : ""}`} disabled={!scene.enabled} onClick={() => { setSelectedScene(scene.scene); setClientError(""); keyRef.current = crypto.randomUUID(); }}><strong>{scene.label}</strong><span>{scene.capability_status === "verified" ? "已验证可用" : "暂不可用"}</span>{scene.disabled_reason && <small>{scene.disabled_reason}</small>}</button>)}
        </div>
        <div className="section-heading"><span className="step-index">01</span><div><h2>达人筛选条件</h2><p>系统会先转换并校验需求，合法后才申请浏览器资源。</p></div></div>
        <div className="capability-banner"><ShieldCheck size={18} /><div><strong>已核验能力版本</strong><span>{cap.capability_version}</span></div><em>{cap.fields.filter((field) => !field.disabled_reason).length} 项条件可用</em></div>
        {selectedScene === "live_square" ? <div className="field-grid">
          <label className="field full"><span>达人昵称 / 平台 ID <i>选填</i></span><input aria-label="直播达人昵称或平台ID" value={liveForm.keyword ?? ""} onChange={(event) => setLiveForm((current) => ({ ...current, keyword: event.target.value || null }))} placeholder={selectedPlatform === "douyin_xingtu" ? "输入达人昵称、抖音号或星图ID" : "输入达人快手ID或昵称"} /><small>可留空；与直播筛选条件至少选择一项。</small></label>
          <label className="field"><span>目标达人数量 <i>必填</i></span><div className="number-field"><input aria-label="直播目标达人数量" type="number" min={cap.target_count_min} max={Math.min(70, cap.target_count_max)} step={1} value={liveForm.target_count} onChange={(event) => setLiveForm((current) => ({ ...current, target_count: Number(event.target.value) }))} required /><b>位</b></div><small>默认 {cap.target_count_default}，单任务最多 70 位（两平台统一）。</small></label>
          <LiveFilterFields fields={cap.fields.filter((field) => field.field !== "keyword")} values={liveForm.live_filters} onChange={(next) => setLiveForm((current) => ({ ...current, live_filters: next }))} />
          <div className="profile-exclusion"><ShieldCheck size={15} />筛选会在平台直播广场真实应用并校验请求；达到 70 位有效达人后结束，候选不足会如实标记部分完成。</div>
        </div> : selectedPlatform === "douyin_xingtu" ? <div className="field-grid">
          {keywordField && <CapabilityInput field={keywordField} form={form} update={update} setForm={setForm} />}
          <fieldset className="capability-group"><legend>背景信息</legend><p>达人自身属性</p><div className="field-grid">{backgroundFields.map((field) => <CapabilityInput key={field.field} field={field} form={form} update={update} setForm={setForm} />)}</div></fieldset>
          <fieldset className="capability-group"><legend>受众画像</legend><p>连接深度、粉丝量与唯一一种画像</p><div className="field-grid">{audienceFields.map((field) => <CapabilityInput key={field.field} field={field} form={form} update={update} setForm={setForm} />)}</div><div className="profile-exclusion"><ShieldCheck size={15} />巨量星图仅允许观众画像与粉丝画像二选一；选择一侧会清空另一侧。</div></fieldset>
          <label className="field"><span>目标达人数量 <i>必填</i></span><div className="number-field"><input type="number" min={cap.target_count_min} max={cap.target_count_max} step={1} value={form.target_count} onChange={(e) => update("target_count", Number(e.target.value))} required /><b>位</b></div><small>允许 {cap.target_count_min}—{cap.target_count_max}，默认 {cap.target_count_default}。平台实际可发现数量受当前搜索能力边界限制。</small></label>
        </div> : <JuxingCapabilityInputs fields={cap.fields} form={juxingForm} setForm={setJuxingForm} targetMin={cap.target_count_min} targetMax={cap.target_count_max} />}
        <div className="fixed-setting"><span>排序方式</span><strong>{cap.fixed_sort_label}</strong><small>固定由当前平台能力决定</small></div>
        {(clientError || submit.isError) && <div className="form-error" role="alert"><AlertCircle size={17} /><div><strong>{clientError || friendlyError(submit.error)}</strong>{submit.error instanceof ApiError && submit.error.detail.field_errors?.map((item) => <span key={item.path}>{item.path}：{item.message}</span>)}</div></div>}
      </section>
      <aside className="submit-card">
        <div className="section-heading compact"><span className="step-index">02</span><div><h2>确认提交</h2><p>提交后立即获得任务编号。</p></div></div>
        <dl><div><dt>平台 / 场景</dt><dd>{platformLabel[selectedPlatform]} · {sceneLabel}</dd></div><div><dt>已选条件</dt><dd>{summary.length ? `${summary.length} 项` : "待填写"}</dd></div><div><dt>目标数量</dt><dd>{activeForm.target_count} 位</dd></div><div><dt>排序</dt><dd>{cap.fixed_sort_label}</dd></div></dl>
        {summary.length > 0 && <ul className="condition-summary">{summary.map((item) => <li key={item}>{item}</li>)}</ul>}
        <div className="submit-assurance"><Check size={16} /><span>重复点击或网络重试不会创建第二个任务</span></div>
        <button className="button primary submit-button" disabled={submit.isPending}>{submit.isPending ? <><LoaderCircle className="spin" size={18} />正在可靠提交</> : <><WandSparkles size={18} />提交采集任务</>}</button>
        <p className="submit-note">提交不代表立即访问平台。需求将经过模型转换、Schema 校验和确定性业务校验。</p>
      </aside>
    </form>
  </div>;
}

const JUXING_QUOTE_TIERS: Array<{ key: "seconds_1_20" | "seconds_21_60" | "seconds_60_plus"; label: string }> = [
  { key: "seconds_1_20", label: "1-20秒视频" },
  { key: "seconds_21_60", label: "21-60秒视频" },
  { key: "seconds_60_plus", label: "60秒以上视频" },
];
type JuxingQuotes = NonNullable<RequirementFormV3["juxing_video_quotes"]>;
const EMPTY_JUXING_QUOTES: JuxingQuotes = { seconds_1_20: null, seconds_21_60: null, seconds_60_plus: null };

function JuxingFollowersField({ field, value, onChange }: { field: CapabilityField; value: CountRangeValue | null; onChange: (value: CountRangeValue | null) => void }) {
  const preset = field.options.find((option) => option.range && Number(option.range.min) === value?.min && (option.range.max === null ? value?.max === null : Number(option.range.max) === value?.max));
  const custom = Boolean(value && !preset);
  const inWan = (raw: number | null) => raw === null ? "" : String(raw / 10_000);
  const fromWan = (raw: string) => raw === "" ? null : Math.round(Number(raw) * 10_000);
  const setRange = (min: number | null, max: number | null) => onChange(min === null && max === null ? null : { min, max, unit: "count" });
  return <div className="field full">
    <span>{field.label} <i>已核验</i></span>
    <select aria-label={field.label} value={preset?.value ?? (value ? "custom" : "")} onChange={(event) => {
      const raw = event.target.value;
      if (raw === "custom") { if (!value) onChange({ min: 0, max: null, unit: "count" }); return; }
      const option = field.options.find((item) => item.value === raw);
      if (!option) { onChange(null); return; }
      if (option.range) onChange({ min: option.range.min === null ? null : Number(option.range.min), max: option.range.max === null ? null : Number(option.range.max), unit: "count" });
    }}>
      <option value="">全部／不限</option>
      {field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      <option value="custom">自定义（万）</option>
    </select>
    {custom && <div className="range-fields juxing-range"><input aria-label="粉丝下限（万）" type="number" min="0" step="any" value={inWan(value?.min ?? null)} onChange={(event) => setRange(fromWan(event.target.value), value?.max ?? null)} /><b>—</b><input aria-label="粉丝上限（万）" type="number" min="0" step="any" value={inWan(value?.max ?? null)} onChange={(event) => setRange(value?.min ?? null, fromWan(event.target.value))} /><em>万</em></div>}
    <small>预设区间来自平台真实控件；自定义按“万”输入后换算为平台整数 count。</small>
  </div>;
}

function JuxingQuoteField({ value, onChange }: { value: RequirementFormV3["juxing_video_quotes"]; onChange: (value: RequirementFormV3["juxing_video_quotes"]) => void }) {
  const [tier, setTier] = useState<keyof JuxingQuotes | "">("");
  const selected = JUXING_QUOTE_TIERS.find((item) => value?.[item.key]);
  // Only follow the value when it actually names a tier.  Clearing the previous tier's range on
  // a tier switch makes `value` null for one render; resetting the control there would bounce the
  // operator back to「全部／不限」and hide the inputs they just switched to.
  useEffect(() => { if (selected?.key) setTier(selected.key); }, [selected?.key]);
  const range = tier ? value?.[tier] ?? null : null;
  function updateBound(field: "min" | "max", raw: string) {
    if (!tier) return;
    const current = value?.[tier] ?? { min: null, max: null, unit: "yuan" as const };
    const next = { ...current, [field]: raw === "" ? null : Number(raw), unit: "yuan" as const };
    if (next.min === null && next.max === null) onChange(null);
    else onChange({ ...EMPTY_JUXING_QUOTES, [tier]: next });
  }
  return <div className="field full">
    <span>视频报价 <i>已核验</i></span>
    <select aria-label="报价档位" value={tier} onChange={(event) => {
      const next = event.target.value as keyof JuxingQuotes | "";
      setTier(next);
      if (!next) { onChange(null); return; }
      const existing = value?.[next] ?? null;
      onChange(existing ? { ...EMPTY_JUXING_QUOTES, [next]: existing } : null);
    }}>
      <option value="">全部／不限</option>
      {JUXING_QUOTE_TIERS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
    </select>
    {tier && <div className="range-fields juxing-range"><input aria-label="报价下限（元）" type="number" min="0" step="any" value={range?.min ?? ""} onChange={(event) => updateBound("min", event.target.value)} /><b>—</b><input aria-label="报价上限（元）" type="number" min="0" step="any" value={range?.max ?? ""} onChange={(event) => updateBound("max", event.target.value)} /><em>元</em></div>}
    <small>一次只按一个报价档位筛选；平台整数 = 元 × 1000；留空表示该边界不限。</small>
  </div>;
}

function JuxingCapabilityInputs({ fields, form, setForm, targetMin, targetMax }: { fields: CapabilityField[]; form: RequirementFormV3; setForm: Dispatch<SetStateAction<RequirementFormV3>>; targetMin: number; targetMax: number }) {
  const keyword = fields.find((field) => field.field === "keyword");
  const contentType = fields.find((field) => field.field === "content_type");
  const followers = fields.find((field) => field.field === "followers");
  const region = fields.find((field) => field.field === "region");
  const quotes = fields.filter((field) => field.field.startsWith("video_quote_"));
  return <div className="field-grid">
    {keyword && <label className="field full"><span>{keyword.label} <i>已核验</i></span><div className="input-with-icon"><Search size={18} /><input value={form.keyword ?? ""} onChange={(event) => setForm((current) => ({ ...current, keyword: event.target.value || null }))} placeholder="例如：母婴" /></div><small>按内容关键词查找；原文不会被模型改写。</small></label>}
    {contentType && <label className="field"><span>{contentType.label} <i>已核验</i></span><select aria-label={contentType.label} value={form.content_types[0] ?? ""} onChange={(event) => setForm((current) => ({ ...current, content_types: event.target.value ? [event.target.value] : [] }))}><option value="">全部／不限</option>{contentType.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select><small>当前开放平台真实类目「{contentType.options.length}」个；单任务选择一个一级类目。</small></label>}
    {followers && <JuxingFollowersField field={followers} value={form.followers} onChange={(value) => setForm((current) => ({ ...current, followers: value }))} />}
    {region && <RegionField field={region} value={form.creator_regions} onChange={(value) => setForm((current) => ({ ...current, creator_regions: value }))} />}
    {quotes.length === 3 && <JuxingQuoteField value={form.juxing_video_quotes} onChange={(value) => setForm((current) => ({ ...current, juxing_video_quotes: value }))} />}
    <label className="field"><span>目标达人数量 <i>必填</i></span><div className="number-field"><input type="number" min={targetMin} max={targetMax} step={1} value={form.target_count} onChange={(event) => setForm((current) => ({ ...current, target_count: Number(event.target.value) }))} required /><b>位</b></div><small>当前环境允许 {targetMin}—{targetMax} 位；上限由服务端能力配置决定。</small></label>
  </div>;
}

function selectedJuxingConditionSummary(form: RequirementFormV3, fields: CapabilityField[]) {
  const result: string[] = [];
  if (form.keyword?.trim()) result.push(`关键词：${form.keyword.trim()}`);
  if (form.content_types.length) {
    const field = fields.find((item) => item.field === "content_type");
    result.push(`内容类型：${form.content_types.map((value) => field?.options.find((option) => option.value === value)?.label ?? value).join("、")}`);
  }
  if (form.followers) {
    const field = fields.find((item) => item.field === "followers");
    const preset = field?.options.find((option) => option.range && Number(option.range.min) === form.followers?.min && (option.range.max === null ? form.followers?.max === null : Number(option.range.max) === form.followers?.max));
    const wan = (value: number | null | undefined) => value === null || value === undefined ? "不限" : `${value / 10_000}万`;
    result.push(`粉丝数量：${preset?.label ?? `${wan(form.followers.min)}—${wan(form.followers.max)}`}`);
  }
  if (form.creator_regions.length) {
    const field = fields.find((item) => item.field === "region");
    const labels = form.creator_regions.map((item) => {
      const province = field?.region_tree.find((node) => node.value === item.province_code)?.label ?? item.province_code;
      return item.city ? `${province}/${item.city}` : province;
    });
    result.push(`达人地域：${labels.join("、")}`);
  }
  const quoteTier = JUXING_QUOTE_TIERS.find((item) => form.juxing_video_quotes?.[item.key]);
  if (quoteTier && form.juxing_video_quotes) {
    const range = form.juxing_video_quotes[quoteTier.key];
    const bound = (value: number | null | undefined) => value === null || value === undefined ? "不限" : `${value} 元`;
    result.push(`视频报价：${quoteTier.label} ${bound(range?.min)}—${bound(range?.max)}`);
  }
  return result;
}

type FormUpdate = <K extends keyof RequirementFormV2>(key: K, value: RequirementFormV2[K]) => void;

function CapabilityInput({ field, form, update, setForm }: { field: CapabilityField; form: RequirementFormV2; update: FormUpdate; setForm: Dispatch<SetStateAction<RequirementFormV2>> }) {
  if (field.field === "keyword") return <label className="field full"><span>{field.label} <i>已核验</i></span><div className="input-with-icon"><Search size={18} /><input value={form.keyword ?? ""} onChange={(e) => update("keyword", e.target.value || null)} placeholder="例如：宠物、母婴辅食、户外露营" /></div><small>按达人内容关键词查找。关键词原文不会被模型改写。</small></label>;
  if (field.field === "gender") return <SelectField field={field} value={form.creator_gender} onChange={(value) => update("creator_gender", value as RequirementFormV2["creator_gender"])} />;
  if (field.field === "education") return <SelectField field={field} value={form.creator_education} onChange={(value) => update("creator_education", value as RequirementFormV2["creator_education"])} />;
  if (field.field === "yellow_v") return <SelectField field={field} value={form.yellow_v_certification} onChange={(value) => update("yellow_v_certification", value as RequirementFormV2["yellow_v_certification"])} />;
  if (field.field === "region") return <RegionField field={field} value={form.creator_regions} onChange={(value) => update("creator_regions", value)} />;
  if (field.field === "connection_users") return <ConnectionField field={field} value={form.connection_users} onChange={(value) => update("connection_users", value)} />;
  if (field.field === "followers") return <FollowersField field={field} value={form.followers} onChange={(value) => update("followers", value)} />;
  if (field.field === "viewer_profile" || field.field === "fan_profile") return <ProfileField field={field} value={form[field.field]} onChange={(value) => setForm((current) => ({ ...current, [field.field]: value, [field.field === "viewer_profile" ? "fan_profile" : "viewer_profile"]: value ? null : current[field.field === "viewer_profile" ? "fan_profile" : "viewer_profile"] }))} />;
  return null;
}

function SelectField({ field, value, onChange }: { field: CapabilityField; value: string | null; onChange: (value: string | null) => void }) {
  return <label className="field"><span>{field.label} <i>已核验</i></span><select value={value ?? ""} onChange={(event) => onChange(event.target.value || null)}><option value="">全部／不限</option>{field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
}

export type RegionSelectionValue = { province_code: string; city?: string | null };
function RegionField({ field, value, onChange }: { field: CapabilityField; value: RegionSelectionValue[]; onChange: (value: RegionSelectionValue[]) => void }) {
  const [province, setProvince] = useState("");
  const [city, setCity] = useState("");
  const node = field.region_tree.find((item) => item.value === province);
  function commit(provinceCode: string, cityValue: string) {
    if (!provinceCode) return;
    let next = value.filter((item) => item.province_code !== provinceCode || (cityValue ? item.city : false));
    if (cityValue) next = next.filter((item) => !(item.province_code === provinceCode && !item.city));
    const candidate = { province_code: provinceCode, ...(cityValue ? { city: cityValue } : {}) };
    if (!next.some((item) => item.province_code === provinceCode && (item.city ?? null) === (cityValue || null))) next.push(candidate);
    onChange(next);
  }
  function add() { commit(province, city); }
  return <div className="field full"><span>{field.label} <i>已核验</i></span><div className="region-picker"><select aria-label="省级地域" value={province} onChange={(event) => { const next = event.target.value; setProvince(next); setCity(""); if (next) commit(next, ""); }}><option value="">选择省份</option>{field.region_tree.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select><select aria-label="二级地域" value={city} onChange={(event) => { const next = event.target.value; setCity(next); if (province) commit(province, next); }} disabled={!node?.children.length}><option value="">整省</option>{node?.children.map((item) => <option value={item.label} key={item.value}>{item.label}</option>)}</select><button type="button" className="button secondary" onClick={add}>添加</button></div><div className="selection-chips">{value.map((item) => { const provinceLabel = field.region_tree.find((nodeItem) => nodeItem.value === item.province_code)?.label ?? item.province_code; const label = item.city ? `${provinceLabel} / ${item.city}` : provinceLabel; return <button type="button" key={`${item.province_code}:${item.city ?? ""}`} onClick={() => onChange(value.filter((current) => current !== item))}>{label} ×</button>; })}</div></div>;
}

function RangeInputs({ value, constraint, onChange }: { value: RangeValue | null; constraint?: { min: number; max: number } | null; onChange: (value: RangeValue | null) => void }) {
  function bound(key: "min" | "max", raw: string) { const next = { min: value?.min ?? null, max: value?.max ?? null, unit: "ten_thousand_count" as const, [key]: raw === "" ? null : Number(raw) }; onChange(next.min === null && next.max === null ? null : next); }
  return <div className="range-fields"><input aria-label="下限" type="number" step="any" min={constraint?.min ?? 0} max={constraint?.max} value={value?.min ?? ""} placeholder="下限" onChange={(event) => bound("min", event.target.value)} /><b>—</b><input aria-label="上限" type="number" step="any" min={constraint?.min ?? 0} max={constraint?.max} value={value?.max ?? ""} placeholder="上限" onChange={(event) => bound("max", event.target.value)} /><em>w</em></div>;
}

function ConnectionField({ field, value, onChange }: { field: CapabilityField; value: Record<string, RangeValue | null> | null; onChange: (value: Record<string, RangeValue | null> | null) => void }) {
  function change(dimension: CapabilityDimension, range: RangeValue | null) { const next = { ...(value ?? {}), [dimension.key]: range }; if (!range) delete next[dimension.key]; onChange(Object.keys(next).length ? next : null); }
  return <div className="field full"><span>{field.label} <i>已核验</i></span><div className="dimension-ranges">{field.dimensions.map((dimension) => <label key={dimension.key}><span>{dimension.label}</span><RangeInputs value={value?.[dimension.key] ?? null} constraint={dimension.range_constraints} onChange={(range) => change(dimension, range)} /></label>)}</div></div>;
}

function FollowersField({ field, value, onChange }: { field: CapabilityField; value: RangeValue | null; onChange: (value: RangeValue | null) => void }) {
  const preset = field.options.find((option) => option.range && Number(option.range.min) === value?.min && (option.range.max === null ? value?.max === null : Number(option.range.max) === value?.max));
  return <div className="field full"><span>{field.label} <i>已核验</i></span><select aria-label={field.label} value={preset?.value ?? (value ? "custom" : "")} onChange={(event) => { const option = field.options.find((item) => item.value === event.target.value); if (!option) onChange(null); else if (option.range) onChange({ min: option.range.min === null ? null : Number(option.range.min), max: option.range.max === null ? null : Number(option.range.max), unit: "ten_thousand_count" }); else if (option.value === "custom" && !value) onChange({ min: 0, max: null, unit: "ten_thousand_count" }); }}><option value="">全部／不限</option>{field.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>{(value && !preset) && <RangeInputs value={value} constraint={field.range_constraints} onChange={onChange} />}</div>;
}

function ProfileField({ field, value, onChange }: { field: CapabilityField; value: AudienceProfile | null; onChange: (value: AudienceProfile | null) => void }) {
  function change(dimension: CapabilityDimension, option: string, selected: boolean) { const next = value ? { ...value } : emptyProfile(); if (dimension.control === "single-select") next.gender = option || null; else { const key = dimension.key as "age" | "device_brand" | "city_level" | "crowd"; const current = next[key]; next[key] = selected ? [...current, option] : current.filter((item) => item !== option); } onChange(next.age.length || next.gender || next.device_brand.length || next.city_level.length || next.crowd.length ? next : null); }
  return <div className="field full profile-field"><span>{field.label} <i>已核验</i></span>{field.dimensions.map((dimension) => <div className="profile-dimension" key={dimension.key}><strong>{dimension.label}</strong>{dimension.control === "single-select" ? <select value={value?.gender ?? ""} onChange={(event) => change(dimension, event.target.value, true)}><option value="">不限</option>{dimension.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <div className="option-grid">{dimension.options.map((option) => { const key = dimension.key as "age" | "device_brand" | "city_level" | "crowd"; const checked = value?.[key].includes(option.value) ?? false; return <label key={option.value}><input type="checkbox" checked={checked} onChange={(event) => change(dimension, option.value, event.target.checked)} />{option.label}</label>; })}</div>}</div>)}</div>;
}

function selectedConditionSummary(form: RequirementFormV2, fields: CapabilityField[]) {
  const result: string[] = [];
  const field = (name: string) => fields.find((item) => item.field === name);
  const label = (name: string, value: string | null) => field(name)?.options.find((item) => item.value === value)?.label ?? value;
  if (form.keyword?.trim()) result.push(`关键词：${form.keyword.trim()}`);
  if (form.creator_gender) result.push(`达人性别：${label("gender", form.creator_gender)}`);
  if (form.creator_regions.length) result.push(`所在地域：${form.creator_regions.length} 项`);
  if (form.creator_education) result.push(`学历：${label("education", form.creator_education)}`);
  if (form.yellow_v_certification) result.push(`黄v：${label("yellow_v", form.yellow_v_certification)}`);
  if (form.connection_users) result.push(`连接用户：${Object.keys(form.connection_users).length} 个区间`);
  if (form.followers) result.push(`粉丝量：${form.followers.min ?? "0"}—${form.followers.max ?? "不限"}w`);
  if (form.viewer_profile) result.push("观众画像：已设置");
  if (form.fan_profile) result.push("粉丝画像：已设置");
  return result;
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
  const juxingCapabilities = useQuery({
    queryKey: ["capabilities", "kuaishou_juxing"],
    queryFn: () => api.capabilities("kuaishou_juxing"),
    enabled: task.data?.platform === "kuaishou_juxing" && task.data?.creator_scene !== "live_square",
    staleTime: 30 * 60 * 1000,
  });
  const liveCapabilities = useQuery({
    queryKey: ["capabilities", task.data?.platform ?? "douyin_xingtu", "live_square"],
    queryFn: () => api.capabilities(task.data?.platform ?? "douyin_xingtu", "live_square"),
    enabled: task.data?.creator_scene === "live_square",
    staleTime: 30 * 60 * 1000,
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
  const taskKind = item.task_kind ?? "collection";
  const juxingTask = item.platform === "kuaishou_juxing";
  const liveTask = item.creator_scene === "live_square";
  const noFeatured = juxingTask || liveTask;
  const sceneLabel = liveTask ? "直播广场" : "短视频广场";
  const juxingRequirement = !liveTask && item.requirement?.schema_version === "requirement_form.v3"
    ? (item.requirement as RequirementFormV3)
    : null;
  const juxingConditions = juxingRequirement ? selectedJuxingConditionSummary(juxingRequirement, juxingCapabilities.data?.fields ?? []) : [];
  const requirementScene = (item.requirement as { creator_scene?: CreatorScene } | null | undefined)?.creator_scene;
  const liveRequirement = liveTask && requirementScene === "live_square"
    ? (item.requirement as LiveRequirementForm)
    : null;
  const liveConditions = liveRequirement ? liveFilterSummary(liveRequirement, liveCapabilities.data?.fields ?? []) : [];
  const conditionRows = liveTask ? liveConditions : juxingConditions;
  const remainingToTarget = Math.max(0, item.counts.target_count - item.counts.valid_count);
  const backfillPending = Math.max(0, item.counts.valid_count - item.counts.profile_complete_count);
  const completeDetail = backfillPending > 0 ? `待补采 ${backfillPending} 位` : "全部完整";
  // 聚星没有星图 F06 两组精选集合：绝不能用一个恒为 0 的「精选完整」卡片暗示缺失。
  const countCards = taskKind === "collection"
    ? [
        ["已发现", item.counts.discovered_count, "候选达人"],
        ["有效入库", item.counts.valid_count, `目标 ${item.counts.target_count}${remainingToTarget > 0 ? ` · 还差 ${remainingToTarget} 位` : ""}`],
        ...(noFeatured
          ? [["资料完整", item.counts.profile_complete_count, completeDetail] as const]
          : [
              ["资料完整", item.counts.profile_complete_count, backfillPending > 0 ? `待补采 ${backfillPending} 位` : "全部完整"] as const,
              ["精选完整", item.counts.featured_complete_count, "F06 双集合"] as const,
            ]),
      ]
    : [
        ["目标达人", item.counts.target_count, taskKindLabel[taskKind]],
        ["已更新", item.counts.valid_count, `目标 ${item.counts.target_count}`],
        ["资料完整", item.counts.profile_complete_count, "F05 模块"],
        ["精选完整", item.counts.featured_complete_count, "F06 双集合"],
  ];
  return <div className="page-wrap">
    <div className="detail-topline"><Link to="/tasks" className="back-link"><ArrowLeft size={17} />任务中心</Link><span>/</span><span>#{shortId(item.root_task_id)}</span></div>
    <PageHeader eyebrow="TASK DETAIL" title={taskTitle(item)} description={`任务 #${item.root_task_id} · ${platformLabel[item.platform ?? "douyin_xingtu"]} · ${sceneLabel}`} actions={<TaskActions task={item} busy={command.isPending} run={(action) => command.mutate(action)} />} />
    <section className="task-hero panel">
      <div className="hero-status"><StatusBadge status={item.status} pulse={!terminalStatuses.has(item.status)} /><h2>{item.stage}</h2><p>{taskMessage(item)}</p></div>
      <ProgressRail status={item.status} kind={taskKind} />
      <div className="hero-meta"><div><span>创建人</span><strong>{item.created_by_name || "系统"}</strong></div><div><span>创建时间</span><strong>{formatDate(item.created_at)}</strong></div><div><span>最近更新</span><strong title="服务端最后一次改动这条任务记录的时间（状态推进、进度保存或人工操作），不代表任务完成时刻">{formatDate(item.updated_at)}</strong></div>{/* 只在任务真正进入终态后展示完成时间，进行中的任务不显示该字段，避免误读为已完成。 */}{item.completed_at && <div><span>首次完成时间</span><strong title="任务第一次进入终态的时间；补采成功后不会改写，最近一次写入见「最近更新」">{formatDate(item.completed_at)}</strong></div>}<div><span>平台 / 场景</span><strong>{platformLabel[item.platform ?? "douyin_xingtu"]} · {sceneLabel}</strong></div><div><span>能力版本</span><strong>{item.capability_version || (taskKind === "collection" ? "历史任务" : "更新任务不适用")}</strong></div></div>
    </section>
    {item.challenge && <ChallengePanel task={item} />}
    {item.intake && <IntakePanel intake={item.intake} />}
    {item.failure_reason || item.field_errors.length > 0 || command.isError ? (
      <section className={attentionPanelClass(item, command.isError)}><AlertCircle size={20} /><div><strong>{attentionTitle(item)}</strong><p>{command.isError ? friendlyError(command.error) : attentionDetail(item)}</p>{item.field_errors.map((error) => <span key={`${error.path}-${error.code}`}>{error.path}：{error.message}</span>)}</div></section>
    ) : null}
    {!command.isError && item.retry_plan?.last_retry_at && terminalStatuses.has(item.status) && (
      <section className="attention-panel neutral"><Clock3 size={20} /><div><strong>上次重试</strong><p>{formatDate(item.retry_plan.last_retry_at)}{item.retry_plan.changed_since_last_retry !== null ? ` · 更新了 ${item.retry_plan.changed_since_last_retry} 位达人的资料` : ""}；当前有效 {item.counts.valid_count}/{item.counts.target_count}，资料完整 {item.counts.profile_complete_count}。</p></div></section>
    )}
    <section className="count-grid">{countCards.map(([label, value, detail]) => <div className="count-card" key={String(label)}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>)}<div className={`count-card ${item.counts.failed_count ? "danger" : ""}`}><span>失败步骤</span><strong>{item.counts.failed_count}</strong><small>可重试项由服务端判定</small></div></section>
    <div className="detail-grid">
      <section className="panel creators-panel"><div className="panel-heading"><div><h2>任务内达人</h2><p>执行中只展示已持久草稿；终态展示任务关联快照。</p></div><span>{creators.data?.pages.flatMap((page) => page.items).length ?? 0} 位可查看</span></div>
        {creators.isLoading ? <SkeletonRows rows={4} /> : creators.isError ? <ErrorState error={creators.error} retry={() => creators.refetch()} /> : !creators.data?.pages[0]?.items.length ? <EmptyState title={terminalStatuses.has(item.status) ? "当前任务没有有效达人" : "达人结果正在形成"} description={terminalStatuses.has(item.status) ? "查看任务状态与失败原因，确认是零结果、部分完成还是执行失败。" : "发现并有效落库后，达人会出现在这里。"} /> : <><div className="creator-list">{creators.data.pages.flatMap((page) => page.items).map((creator) => <CreatorRow key={creator.creator_id} taskId={taskId} creator={creator} />)}</div>{creators.hasNextPage && <div className="pagination"><button className="button secondary" disabled={creators.isFetchingNextPage} onClick={() => creators.fetchNextPage()}>{creators.isFetchingNextPage ? "正在读取" : "查看更多达人"}<ArrowRight size={16} /></button></div>}</>}
      </section>
      {taskKind === "collection" ? <aside className="panel requirement-panel"><div className="panel-heading"><div><h2>需求与执行约束</h2><p>原始需求和执行计划分开留存。</p></div></div><dl><div><dt>平台</dt><dd>{platformLabel[item.platform ?? "douyin_xingtu"]}</dd></div><div><dt>{liveTask ? "关键词 / 平台 ID" : "内容关键词"}</dt><dd>{item.requirement?.keyword || item.keyword || "—"}</dd></div>{conditionRows.filter((condition) => !condition.startsWith("关键词")).map((condition) => { const [label, ...rest] = condition.split("："); return <div key={condition}><dt>{label}</dt><dd>{rest.join("：")}</dd></div>; })}<div><dt>目标数量</dt><dd>{item.counts.target_count} 位</dd></div><div><dt>排序方式</dt><dd>平台默认排序</dd></div><div><dt>来源</dt><dd>{item.source === "product" ? "媒介产品提交" : "系统内部任务"}</dd></div></dl>{item.plan && <details><summary>查看最终执行计划</summary><pre>{JSON.stringify(item.plan, null, 2)}</pre></details>}{item.origin_root_task_id && <Link to={`/tasks/${item.origin_root_task_id}`} className="origin-link"><RotateCcw size={15} />查看来源任务</Link>}</aside> : <aside className="panel requirement-panel"><div className="panel-heading"><div><h2>更新目标</h2><p>批次内每位达人独立采集、独立保存；失败不影响其他达人。</p></div></div><dl><div><dt>平台</dt><dd>{platformLabel[item.platform ?? "douyin_xingtu"]}</dd></div><div><dt>任务类型</dt><dd>{taskKindLabel[taskKind]}</dd></div><div><dt>目标数量</dt><dd>{item.counts.target_count} 位</dd></div><div><dt>已更新</dt><dd>{item.counts.valid_count} 位</dd></div><div><dt>来源</dt><dd>{item.created_by_name || "定时调度"}</dd></div></dl><div className="update-target-list">{(item.update_targets ?? []).map((target) => <div key={target.platform_creator_id}><span>{target.display_name || `达人 ${target.first_position + 1}`}</span><em>{updateTargetStateLabel[target.state] || target.state}</em>{target.failure_reason && <small>{target.failure_reason}</small>}</div>)}</div></aside>}
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
// Fixed wording for reasons whose plain code is not actionable to a media buyer. The scope-aware
// retry explanation is produced separately from `task.retry_plan`; these remain the fallback for
// tasks without a retryable step.
const FAILURE_REASON_MESSAGES = new Map([
  ["SEARCH_EXHAUSTED", "平台已没有更多符合条件的达人。可调整条件后新建任务；本次任务不会自动放宽条件。"],
  ["SEARCH_CAPABILITY_LIMIT", "平台当前分页能力已到边界，任务仍有可用结果。需要更多达人时请新建任务。"],
  ["FEATURED_NOT_ATTEMPTED", "数量已达标，但精选作品步骤尚未执行。"],
  ["PROFILE_SCOPE_INCOMPLETE", "有位达人的主页资料本次未能全部读到（已成功读取的部分和精选作品已经保存）。可点「补采缺失字段」补齐，不会重复创建任务。"],
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

function retryScopeMessage(task: TaskDetail) {
  if ((task.task_kind ?? "collection") !== "collection") return null;
  const plan = task.retry_plan;
  if (!plan || !task.allowed_actions.includes("retry")) return null;
  if (plan.scope === "continue") {
    const base = `已采到 ${task.counts.valid_count}/${task.counts.target_count} 位有效达人，还差 ${plan.remaining_to_target} 位。点击「继续采集」只补数量，不会重新采集已入库达人。`;
    return plan.incomplete_valid_count > 0
      ? `${base} 其中 ${plan.incomplete_valid_count} 位资料不完整，将在数量补足后单独补采。`
      : base;
  }
  return `已采到 ${task.counts.valid_count}/${task.counts.target_count} 位有效达人，其中 ${plan.incomplete_valid_count} 位资料不完整（读取失败或未完成）。点击「补采缺失字段」只补这些达人的缺失部分，不会新增达人。`;
}

function attentionDetail(task: TaskDetail) {
  if (isUserCancelled(task)) return "任务已按你的操作取消，已持久的结果会保留。";
  // A transient platform response can leave one profile module incomplete while everything else —
  // including the persisted results — is fine. Say what happened and that the offered action is
  // real instead of showing a bare internal code (FIX-01 P0-A acceptance wording).
  const scoped = retryScopeMessage(task);
  if (scoped) return task.failure_reason ? `${scoped} 服务端原因：${task.failure_reason}` : scoped;
  const reason = task.failure_reason;
  if (reason === "ACCOUNT_SELECTION_REQUIRED") {
    return "磁力聚星需要选择子账号。当前任务已暂停，请在 Chrome 中选择 cpg果汁（60821564）；完成后系统会重新校验账号身份并继续采集，请勿选择其他子账号。";
  }
  if (reason === "ACCOUNT_SELECTION_TIMEOUT") {
    return "等待选择子账号超过保护窗口，任务已停止。请重新发起任务，并在 Chrome 中选择 cpg果汁（60821564）后继续采集。";
  }
  if (reason && reason.startsWith("SECURITY_CHALLENGE_")) {
    return "任务因平台安全验证未完成而停止。请先完成验证；当前不提供重试。";
  }
  const message = reason ? FAILURE_REASON_MESSAGES.get(reason) : undefined;
  if (message) return message;
  return reason || "请根据字段提示修改后重新提交。";
}

function taskMessage(task: TaskDetail) {
  const juxing = task.platform === "kuaishou_juxing";
  const messages: Partial<Record<TaskStatus, string>> = {
    RECEIVED: "需求已可靠保存，等待转换工作流接管。", PARSING: "正在把原始筛选条件转换为可执行计划，并逐字段校验。",
    QUEUED: "执行计划已通过校验，正在等待采集资源。",
    SEARCHING: juxing ? "正在磁力聚星中按已核验条件发现达人。" : "正在星图中按已核验条件发现达人。",
    COLLECTING: juxing ? "正在采集达人基础、传播、作品与受众资料。" : "正在采集达人主页资料与两组精选作品。",
    PERSISTING: "数据已采集，正在发布任务不可变快照。",
    COMPLETED: "目标链路已完成，可查看发布快照。", PARTIAL_COMPLETED: "部分结果已保存，请查看失败步骤与可用操作。",
    FAILED_VALIDATION: "原始需求未能安全映射为执行计划，未申请浏览器资源。", FAILED: "执行未完成，已保存的结果不会丢失。",
    CANCELLING: "取消已受理，正在等待执行中的步骤安全收尾。", CANCELLED: "任务已按你的操作取消，已持久的结果保留。",
    PAUSED_BUDGET: "本次执行预算已用完，可在确认后继续。", WAITING_FOR_LOGIN: "平台会话需要维护，本里程碑暂不提供远程登录入口。",
    WAITING_FOR_ACCOUNT: task.failure_reason === "ACCOUNT_SELECTION_REQUIRED"
      ? "磁力聚星需要选择子账号，请在 Chrome 中选择 cpg果汁（60821564）后继续采集。"
      : "当前平台账号与任务绑定账号不一致，采集已暂停。",
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
      {challenge.challenge_type === "ACCOUNT_SELECTION" ? <div className="challenge-heading"><strong>子账号选择托管</strong><span>{stateLabel[challenge.state] || challenge.state}</span></div> : <div className="challenge-heading"><strong>安全验证托管</strong><span>{stateLabel[challenge.state] || challenge.state}</span></div>}
      <p>{challenge.challenge_type === "ACCOUNT_SELECTION"
        ? (challenge.terminal_message || "磁力聚星需要选择子账号。请在 Chrome 中选择 cpg果汁（60821564）；系统会重新校验账号后继续采集。请勿选择其他子账号。")
        : (challenge.terminal_message || (challenge.requires_user_action ? "请在平台原生页面完成安全验证；系统不会操作验证控件。" : "验证状态已记录，后续恢复由服务端检查决定。"))}</p>
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
      {challenge.challenge_type === "ACCOUNT_SELECTION" && challenge.requires_user_action && <div className="challenge-foot"><Link to="/execution-units" className="button secondary">前往执行单元接管浏览器</Link><span>正确子账号：cpg果汁（60821564）</span></div>}
    </div>
  </section>;
}

function retryActionLabel(task: TaskDetail) {
  const plan = task.retry_plan;
  // Update tasks count creators with the same fields but have no "还差 N 位" goal; keep the
  // neutral wording instead of borrowing the collection wording.
  if (!plan || (task.task_kind ?? "collection") !== "collection") return "重试失败步骤";
  if (plan.scope === "continue") {
    return plan.remaining_to_target > 0 ? `继续采集（还差 ${plan.remaining_to_target} 位）` : "继续采集";
  }
  return plan.incomplete_valid_count > 0 ? `补采缺失字段（${plan.incomplete_valid_count} 位）` : "补采缺失字段";
}

function retryActionConfirm(task: TaskDetail) {
  const plan = (task.task_kind ?? "collection") === "collection" ? task.retry_plan : null;
  if (plan?.scope === "continue") {
    return `本次只补足剩余 ${plan.remaining_to_target} 位有效达人，不会补采已入库达人的缺失资料。是否继续？`;
  }
  if (plan?.scope === "backfill") {
    return `本次只为 ${plan.incomplete_valid_count} 位已入库达人补采缺失资料，不会搜索或新增达人。是否继续？`;
  }
  return "本次只处理未完成的步骤，已成功的内容不会重复采集。是否继续？";
}

function TaskActions({ task, busy, run }: { task: TaskDetail; busy: boolean; run: (action: "cancel" | "continue" | "retry") => void }) {
  return <div className="task-actions">
    {task.allowed_actions.includes("modify_resubmit") && <Link to={`/tasks/new?origin=${task.root_task_id}`} className="button secondary"><RotateCcw size={16} />修改重提</Link>}
    {task.allowed_actions.includes("continue") && <button className="button primary" disabled={busy} onClick={() => run("continue")}><Play size={16} />继续任务</button>}
    {task.allowed_actions.includes("retry") && <button className="button primary" disabled={busy} onClick={() => window.confirm(retryActionConfirm(task)) && run("retry")}><RefreshCcw size={16} />{retryActionLabel(task)}</button>}
    {task.allowed_actions.includes("cancel") && <button className="button danger-button" disabled={busy} onClick={() => window.confirm("确认取消这个任务？已持久的结果会保留。") && run("cancel")}><CircleStop size={16} />取消任务</button>}
  </div>;
}

function ProgressRail({ status, kind = "collection" }: { status: TaskStatus; kind?: TaskKind }) {
  const stages = kind === "collection" ? [{ label: "需求接收", states: ["RECEIVED"] }, { label: "转换校验", states: ["PARSING", "FAILED_VALIDATION"] }, { label: "排队", states: ["QUEUED", "WAITING_FOR_RESOURCE"] }, { label: "发现达人", states: ["SEARCHING"] }, { label: "采集资料", states: ["COLLECTING", "RETRY_WAIT", "WAITING_FOR_LOGIN", "WAITING_FOR_ACCOUNT", "WAITING_FOR_VERIFICATION", "PAUSED_BUDGET"] }, { label: "发布结果", states: ["PERSISTING", "COMPLETED", "PARTIAL_COMPLETED"] }] : [{ label: "排队", states: ["QUEUED", "WAITING_FOR_RESOURCE"] }, { label: "采集资料", states: ["COLLECTING", "RETRY_WAIT", "WAITING_FOR_LOGIN", "WAITING_FOR_ACCOUNT", "WAITING_FOR_VERIFICATION", "PAUSED_BUDGET"] }, { label: "发布结果", states: ["PERSISTING", "COMPLETED", "PARTIAL_COMPLETED"] }];
  const current = Math.max(0, stages.findIndex((stage) => stage.states.includes(status)));
  return <div className="progress-rail">{stages.map((stage, index) => <div className={`${index < current ? "done" : index === current ? "current" : ""}`} key={stage.label}><span>{index < current ? <Check size={14} /> : index + 1}</span><b>{stage.label}</b></div>)}</div>;
}

// 「任务内达人」与「达人库」共用同一套指标名称、取值与格式化规则：字段都从快照 JSONB 按达人库
// 读模型使用的同名字段键读取，缺失即显示“暂无数据”，不推测数值。CPM/CPE 与达人库列表行一致地
// 并列展示 21–60 秒与 60 秒以上两档平台原始值。聚星没有这些指标，因此按平台切换指标组，而不是
// 让它们以「暂无数据」占位或把聚星指标冒充星图指标。
function CreatorRow({ taskId, creator }: { taskId: string; creator: CreatorSummary }) {
  const platform = creator.platform ?? "douyin_xingtu";
  const juxing = platform === "kuaishou_juxing";
  const view = snapshotCreatorView(
    creator.payload,
    {
      creator_id: creator.creator_id,
      platform_creator_id: creator.platform_creator_id,
      snapshot_id: creator.snapshot_id,
      observed_at: creator.observed_at,
    },
    platform,
  );
  const name = view.display_name || `达人 ${creator.first_position + 1}`;
  return <Link className="creator-row" to={`/tasks/${taskId}/creators/${creator.creator_id}`} aria-label={`查看达人 ${name} 详情`}>
    <div className="creator-rank">{String(creator.first_position + 1).padStart(2, "0")}</div>
    <div className="creator-avatar">{view.avatar_uri ? <img src={view.avatar_uri} alt="" /> : <UserRound size={20} />}</div>
    <div className="creator-copy">
      <strong>{name}</strong>
      <span>{juxing ? (view.content_theme_labels.join(" · ") || "内容类型暂无数据") : (creatorTags(view) || "标签暂无数据")}</span>
      <em>{juxing ? "快手ID" : "平台 ID"} {creator.platform_creator_id}</em>
    </div>
    {juxing ? (
      <>
        <div className="creator-stat"><span>粉丝</span><strong>{numberText(view.followers.value)}</strong></div>
        <div className="creator-stat"><span>月涨粉率</span><strong>{ratioMetric(view.monthly_follower_growth_rate)}</strong></div>
        <div className="creator-stat"><span>互动 / 完播</span><strong>{ratioMetric(view.interaction_rate)} / {ratioMetric(view.completion_rate)}</strong></div>
        <div className="creator-stat"><span>播放中位数</span><strong>{numberText(view.play_median.value)}</strong></div>
      </>
    ) : (
      <>
        <div className="creator-stat"><span>粉丝</span><strong>{numberText(view.followers.value)}</strong></div>
        <div className="creator-stat"><span>月深度用户</span><strong>{rawMetric(view.monthly_deep_users)}</strong></div>
        <div className="creator-stat engagement"><span>互动 / 完播原始值</span><strong>{rawMetric(view.interaction_rate)} / {rawMetric(view.completion_rate)}</strong></div>
        <div className="creator-stat commercial"><span>CPM / CPE 原始值</span><strong>{rawMetric(view.expected_cpm_21_60)} / {rawMetric(view.expected_cpe_21_60)}</strong><small>21–60 秒 · 60 秒以上 {rawMetric(view.expected_cpm_60_plus)} / {rawMetric(view.expected_cpe_60_plus)}</small></div>
      </>
    )}
    <span className={`view-label ${creator.view_kind}`}>{creator.view_kind === "draft" ? "执行中草稿" : "已发布快照"}</span>
    <ChevronRight size={18} />
  </Link>;
}

/** 达人标签：达人类型与行业标签，缺失的维度直接省略，不使用占位词。 */
function creatorTags(creator: Pick<CreatorLibrarySummary, "creator_type_label" | "industry_labels">) {
  return [creator.creator_type_label, ...creator.industry_labels].filter(Boolean).join(" · ");
}

/**
 * 统一的达人详情视图（CD-02）。
 *
 * 「任务中心 → 任务详情 → 达人详情」与「达人库 → 达人详情」共用 `CreatorProfile`：左侧身份资料卡
 * 与 5 个业务分区完全一致，两个入口各自负责取数：
 * - 任务入口读任务自己的不可变快照（`/api/tasks/{id}/creators/{cid}`），因此展示的是该任务当时
 *   采集到的观测值，并额外保留任务快照特有的「精选作品」与草稿提示。
 * - 达人库入口读达人库当前投影（`/api/creator-library/{cid}`），额外展示该入口独有的合作报价与
 *   历史快照；任务快照里不存在这两类数据，因此任务入口不渲染，而不是用空值伪造。
 */
/**
 * 字段来源抽屉（`数据质量与字段来源`）。
 *
 * CD-03 需求 4.10 移除了左栏的「数据来源」入口，字段来源、单位、周期与观测时间数据本身并未删除；
 * 抽屉由本组件作为左栏以外的覆层挂载，任务入口与达人库入口都能打开，`open` 由父级控制。
 */
function ProvenancePanel({ creator, payload }: { creator: CreatorLibraryDetail; payload: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const catalog = useFieldCatalog(creator.platform);
  const index = useMemo(() => indexCatalog(catalog), [catalog]);
  return <>
    <p className="rail-snapshot-note">
      平台字段的状态、单位、周期与观测时间见
      <button className="link-button" type="button" onClick={() => setOpen(true)}>字段来源</button>
      {creator.latest_snapshot_id ? `（最新不可变快照 ${creator.latest_snapshot_id}）` : ""}。
    </p>
    <ProvenanceDrawer
      open={open}
      onClose={() => setOpen(false)}
      payload={payload}
      index={index}
      moduleStatuses={creator.module_statuses}
      fieldSources={creator.field_sources}
      collectedCount={creator.collected_field_count}
      failedCount={creator.failed_field_count}
    />
  </>;
}

function CreatorDetailView({ creator, profilePayload, platform = "douyin_xingtu", backTo, backLabel, scopeLabel, description, badgeLabel, badgeTone, notice, contents, videos, historyChapter, actions }: {
  creator: CreatorLibraryDetail;
  profilePayload: Record<string, unknown>;
  platform?: "douyin_xingtu" | "kuaishou_juxing";
  backTo: string;
  backLabel: string;
  scopeLabel: string;
  description?: string;
  badgeLabel: string;
  badgeTone: string;
  notice?: ReactNode;
  /** 两组精选视频集合的真实数据源；由各入口按自己的快照范围提供。 */
  contents?: FeaturedContent;
  /** 「创作能力」的作品观测取数（页面 + 该入口的授权封面地址构造器）；由各入口按自己的快照范围提供。 */
  videos?: ReturnType<typeof useVideoObservations>;
  historyChapter?: ReactNode;
  actions?: ReactNode;
}) {
  return <CreatorProfile
    creator={creator}
    payload={profilePayload}
    platform={platform}
    backTo={backTo}
    backLabel={backLabel}
    scopeLabel={scopeLabel}
    description={description}
    badgeLabel={badgeLabel}
    badgeTone={badgeTone}
    notice={notice}
    contents={contents}
    videos={videos?.page}
    videosLoading={videos?.loading}
    videosError={videos?.error}
    onRetryVideos={videos?.onRetry}
    videoCoverUrl={videos?.coverUrl}
    historyChapter={historyChapter}
    actions={actions}
    overlay={<ProvenancePanel creator={creator} payload={profilePayload} />}
  />;
}

/**
 * 精选视频集合（CD-04）的取数适配。
 *
 * 两个入口的数据范围不同、形状相同：任务入口读**本任务快照**的集合，达人库入口读该达人**最新快照**
 * 的集合。卡片字段是 `FieldObservation` 封套（数字为 `{kind, amount, bound}`），这里只做解包与
 * 归一化，不推测缺失值、不构造作品链接：作品链接只取平台返回的 `canonical_link` / `link`。
 */
function featuredCardView(outer: Record<string, unknown>, position: number): FeaturedCardView {
  // The task endpoint returns the card payload at the top level; the library endpoint returns the
  // `featured_cards` row shape (`{card_id, position, cover_status, truncated_fields, payload}`).
  // Reading through `payload` here gives both entries exactly one card shape.
  const card = (
    outer.payload && typeof outer.payload === "object" && !Array.isArray(outer.payload)
      ? outer.payload
      : outer
  ) as Record<string, unknown>;
  const cover = (card.cover && typeof card.cover === "object" ? card.cover : {}) as Record<string, unknown>;
  const asText = (value: unknown) => (typeof value === "string" && value.trim() ? value : null);
  return {
    card_id: asText(card.card_id) ?? asText(outer.card_id),
    position: Number.isFinite(Number(outer.position))
      ? Number(outer.position)
      : Number.isFinite(Number(card.position))
        ? Number(card.position)
        : position,
    platform_content_id: asText(card.platform_content_id),
    local_key: asText(card.local_key),
    canonical_link: asText(card.canonical_link),
    link_from_fields: asText(cardFieldValue(card, "link")),
    cover_object_id: asText(cover.object_id) ?? asText(card.cover_object_id) ?? asText(outer.cover_object_id),
    cover_status: String(card.cover_status ?? cover.status ?? outer.cover_status ?? "NOT_ATTEMPTED"),
    title: asText(cardFieldValue(card, "title")),
    subtitle: asText(cardFieldValue(card, "subtitle")),
    truncated_fields: Array.isArray(outer.truncated_fields)
      ? outer.truncated_fields.map(String)
      : Array.isArray(card.truncated_fields)
        ? card.truncated_fields.map(String)
        : [],
    play: cardFieldValue(card, "play"),
    like: cardFieldValue(card, "like"),
    comment: cardFieldValue(card, "comment"),
  };
}

function featuredCollectionView(
  type: "excellent_reach" | "excellent_seeding",
  page: ContentPage | undefined,
): FeaturedCollectionView | null {
  if (!page) return null;
  return {
    collection_type: type,
    status: page.status,
    view_kind: page.view_kind,
    observed_at: page.observed_at ?? null,
    coverage_gaps: page.coverage_gaps ?? [],
    // A partial or malformed response must degrade to an empty grid, never break the chapter.
    cards: Array.isArray(page.cards)
      ? page.cards.map((card, index) => featuredCardView(card, index))
      : [],
  };
}

/**
 * 两组精选集合 + 每个入口各自的封面地址构造器。
 *
 * 封面统一走本项目对象存储的授权端点（任务按 root_task_id 授权，达人库按 creator_id 授权），
 * 因此不使用平台签名外链——那些 URL 会过期。
 */
function useFeaturedContent(
  scope: { kind: "task"; taskId: string; creatorId: string } | { kind: "library"; creatorId: string },
  enabled = true,
): FeaturedContent {
  const taskScoped = scope.kind === "task";
  const fetchType = (type: "excellent_reach" | "excellent_seeding") =>
    taskScoped
      ? api.contents((scope as { taskId: string }).taskId, scope.creatorId, type)
      : api.creatorLibraryContents(scope.creatorId, type);
  const reach = useQuery({
    queryKey: ["featured", scope.kind, scope.creatorId, (scope as { taskId?: string }).taskId ?? "", "excellent_reach"],
    queryFn: () => fetchType("excellent_reach"),
    enabled,
  });
  const seeding = useQuery({
    queryKey: ["featured", scope.kind, scope.creatorId, (scope as { taskId?: string }).taskId ?? "", "excellent_seeding"],
    queryFn: () => fetchType("excellent_seeding"),
    enabled,
  });
  const coverUrl = taskScoped
    ? (objectId: string) =>
        `/api/tasks/${(scope as { taskId: string }).taskId}/covers/${encodeURIComponent(objectId)}`
    : (objectId: string) => api.creatorLibraryCover(scope.creatorId, objectId);
  return {
    reach: featuredCollectionView("excellent_reach", reach.data),
    seeding: featuredCollectionView("excellent_seeding", seeding.data),
    coverUrl,
    loading: reach.isLoading || seeding.isLoading,
    error: reach.error ?? seeding.error ?? null,
    onRetry: () => {
      void reach.refetch();
      void seeding.refetch();
    },
  };
}

/**
 * 「创作能力 → 最新视频表现」的作品观测取数（DATA-02）。
 *
 * 与精选集合同一套范围语义：任务入口读本任务不可变快照的观测，达人库入口读该达人当前快照的观测。
 * 一次取回两个集合（不传 `module_key`），由面板按当前选中的集合过滤，保证图表与列表始终同源；
 * 封面地址也按入口授权（任务按 root_task_id，达人库按 creator_id），不使用平台签名外链。
 * `retry` 语义沿用全局 QueryClient，与其它只读查询一致。
 */
function useVideoObservations(
  scope: { kind: "task"; taskId: string; creatorId: string } | { kind: "library"; creatorId: string },
  enabled = true,
): {
  page: CreatorVideoPage | null;
  coverUrl: (objectId: string) => string;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
} {
  const taskScoped = scope.kind === "task";
  const taskId = (scope as { taskId?: string }).taskId ?? "";
  const query = useQuery({
    queryKey: ["videos", scope.kind, scope.creatorId, taskId],
    queryFn: () =>
      taskScoped
        ? api.taskCreatorVideos(taskId, scope.creatorId)
        : api.creatorLibraryVideos(scope.creatorId),
    enabled,
  });
  const coverUrl = taskScoped
    ? (objectId: string) => `/api/tasks/${taskId}/covers/${encodeURIComponent(objectId)}`
    : (objectId: string) => api.creatorLibraryCover(scope.creatorId, objectId);
  return {
    page: query.data ?? null,
    coverUrl,
    loading: query.isLoading,
    error: query.error ?? null,
    onRetry: () => {
      void query.refetch();
    },
  };
}

/**
 * 报价与历史（CD-04 调整）：报价数据本身不在「商业能力」内展示，改由本入口的独立章节承载。
 *
 * 任务入口只有本任务的不可变快照，报价来自快照内 `commercial.cooperation_offers` 的平台原值；
 * 这与达人库入口读 `douyin_xingtu_creator_quote_observations`（跨任务、按合作形式取最新）是**两个
 * 不同数据范围**，因此不把任务的快照报价与达人库的当前报价混为一谈。
 */
function taskSnapshotQuotes(payload: Record<string, unknown>): CreatorLibraryQuote[] {
  const modules = (payload.modules && typeof payload.modules === "object" ? payload.modules : {}) as Record<string, unknown>;
  const commercial = (modules.commercial && typeof modules.commercial === "object" ? modules.commercial : {}) as Record<string, unknown>;
  const fields = Array.isArray(commercial.fields) ? commercial.fields : [];
  const offer = fields.find(
    (entry) => entry && typeof entry === "object" && (entry as Record<string, unknown>).field_key === "cooperation_offers",
  ) as Record<string, unknown> | undefined;
  if (!offer || offer.status !== "COLLECTED") return [];
  const value = (offer.value && typeof offer.value === "object" ? offer.value : {}) as Record<string, unknown>;
  const rows = Array.isArray(value.data) ? value.data : [];
  const asText = (input: unknown) => (typeof input === "string" && input.trim() ? input : null);
  const observedAt = asText(offer.observed_at) ?? new Date(0).toISOString();
  return rows
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
    .map((row, position) => ({
      snapshot_id: "",
      position,
      cooperation_form: asText(row.desc) ?? asText(row.field),
      settlement_description: asText(row.settlement_desc),
      price_raw: (row.price ?? null) as string | number | null,
      origin_price_raw: (row.origin_price ?? null) as string | number | null,
      observed_at: observedAt,
      offer_raw: row,
    }));
}

export function CreatorDetailPage() {
  const { taskId = "", creatorId = "" } = useParams();
  const creator = useQuery({ queryKey: ["creator", taskId, creatorId], queryFn: () => api.creator(taskId, creatorId) });
  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => api.task(taskId) });
  const platform = creator.data?.platform ?? "douyin_xingtu";
  const juxing = platform === "kuaishou_juxing";
  const live = task.data?.creator_scene === "live_square";
  // 聚星没有星图 F06 精选集合与星图作品观测表：不发起这些请求，也不把空结果伪装成业务数据。
  const contents = useFeaturedContent({ kind: "task", taskId, creatorId }, Boolean(creator.data) && !juxing && !live);
  const videos = useVideoObservations({ kind: "task", taskId, creatorId }, Boolean(creator.data) && !juxing && !live);
  const catalog = useFieldCatalog(platform);
  const index = useMemo(() => indexCatalog(catalog), [catalog]);
  if (creator.isLoading) return <div className="page-wrap"><LoadingState label="正在读取达人快照" /></div>;
  if (creator.isError || !creator.data) return <div className="page-wrap"><ErrorState error={creator.error} retry={() => creator.refetch()} /></div>;
  const item = creator.data;
  if (live) {
    return <LiveCreatorDetailView
      platform={platform}
      creatorId={item.creator_id}
      platformCreatorId={item.platform_creator_id}
      displayName={payloadDisplayName(item.payload, item.platform_creator_id)}
      payload={item.payload}
      observedAt={item.observed_at}
      backTo={`/tasks/${taskId}`}
      backLabel="返回任务"
      scopeLabel="本任务直播快照"
      liveHref={`/creators/${creatorId}/live`}
    />;
  }
  const view = snapshotCreatorView(
    item.payload,
    {
      creator_id: item.creator_id,
      platform_creator_id: item.platform_creator_id,
      snapshot_id: item.snapshot_id,
      observed_at: item.observed_at,
    },
    platform,
  );
  const snapshotQuotes = juxing ? [] : taskSnapshotQuotes(item.payload);
  return <CreatorDetailView
    creator={view}
    profilePayload={item.payload}
    platform={platform}
    backTo={`/tasks/${taskId}`}
    backLabel="返回任务"
    scopeLabel="本任务采集快照"
    description={juxing
      ? "指标取自本任务采集的不可变快照；字段、单位与统计窗口均为磁力聚星平台原始口径。"
      : "指标取自本任务采集的不可变快照，与达人库当前投影可能不同步；字段口径均为平台原始值。"}
    badgeLabel={item.view_kind === "draft" ? "执行中草稿" : completeLabel(view)}
    badgeTone={item.view_kind === "draft" || !(view.profile_complete && view.pipeline_complete) ? "draft" : "published"}
    notice={item.view_kind === "draft" ? <div className="draft-banner"><Clock3 size={18} /><div><strong>这是执行中的持久草稿</strong><span>字段与作品仍可能补齐；任务发布后将切换到不可变快照。</span></div></div> : undefined}
    contents={juxing ? undefined : contents}
    videos={juxing ? undefined : videos}
    historyChapter={snapshotQuotes.length ? <div className="profile-sections">
      <QuoteTable payload={item.payload} index={index} />
      <section className="panel library-detail-panel"><div className="panel-heading"><div><h2>报价观察</h2><p>本任务快照内每次采集到的报价观察，保留原始报价与合作形式。</p></div><span>{snapshotQuotes.length} 条</span></div><div className="quote-list">{snapshotQuotes.map((quote) => <div key={`${quote.position}-${quote.cooperation_form ?? ""}`}><strong>{quote.cooperation_form || "未标记合作形式"}</strong><span>{quote.settlement_description || "结算说明暂无数据"}</span><b>{quote.price_raw === null ? "暂无报价" : String(quote.price_raw)}</b>{quote.origin_price_raw !== null && quote.origin_price_raw !== quote.price_raw && <em>原价 {String(quote.origin_price_raw)}</em>}<small>{formatDate(quote.observed_at)}</small></div>)}</div></section>
    </div> : undefined}
  />;
}

function completeLabel(creator: CreatorLibraryDetail) {
  return creator.profile_complete && creator.pipeline_complete ? "采集完整" : "数据不完整";
}

/**
 * The platform value a featured card carries for `fieldKey`.
 *
 * Card fields are `FieldObservation` envelopes, so a number arrives as `{kind, amount, bound}` and a
 * title as a plain string; both shapes are unwrapped here.
 */
function cardFieldValue(card: Record<string, unknown>, fieldKey: string): unknown {
  const fields = card.fields;
  if (!Array.isArray(fields)) return null;
  for (const entry of fields) {
    if (!entry || typeof entry !== "object") continue;
    const record = entry as Record<string, unknown>;
    if (record.field_key !== fieldKey) continue;
    return record.value;
  }
  return null;
}

function rawMetric(metric: { raw_value: string | null; value: string | number | null; is_approximate: boolean }) {
  const value = metric.raw_value ?? (metric.value === null ? "暂无数据" : String(metric.value));
  return metric.is_approximate && value !== "暂无数据" ? `≈${value}` : value;
}

function ratioMetric(metric: { raw_value: string | null; value: string | number | null; is_approximate: boolean }) {
  const raw = metric.raw_value ?? metric.value;
  if (raw === null) return "暂无数据";
  const numeric = Number(metric.value ?? raw);
  if (!Number.isFinite(numeric)) return rawMetric(metric);
  const percent = `${(numeric * 100).toFixed(2)}%`;
  return metric.is_approximate ? `≈${percent}` : percent;
}

function numberText(value: string | number | null) { return value === null ? "—" : Number(value).toLocaleString("zh-CN"); }

export function CreatorLibraryPage() {
  const [search, setSearch] = useSearchParams();
  const platform: "douyin_xingtu" | "kuaishou_juxing" =
    search.get("platform") === "kuaishou_juxing" ? "kuaishou_juxing" : "douyin_xingtu";
  const juxing = platform === "kuaishou_juxing";
  const scene: CreatorScene = search.get("creator_scene") === "live_square" ? "live_square" : "video_square";
  const live = scene === "live_square";
  const params = useMemo(() => {
    const value = new URLSearchParams(search);
    return value;
  }, [search]);
  const library = useInfiniteQuery({
    queryKey: ["creator-library", params.toString()],
    queryFn: ({ pageParam }) => {
      const value = new URLSearchParams(params);
      value.set("limit", "20");
      if (pageParam) value.set("cursor", pageParam);
      return api.creatorLibrary(value);
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(search);
    if (value) next.set(key, value); else next.delete(key);
    next.delete("cursor"); setSearch(next);
  };
  /**
   * Switching platform must not carry a Xingtu-only filter into the Juxing query: the server rejects
   * those explicitly, and a stale URL would leave the page on a validation error instead of the list.
   */
  const setPlatform = (value: "douyin_xingtu" | "kuaishou_juxing") => {
    const next = new URLSearchParams();
    if (value === "kuaishou_juxing") next.set("platform", value);
    setSearch(next);
  };
  const setScene = (value: CreatorScene) => {
    const next = new URLSearchParams();
    if (platform === "kuaishou_juxing") next.set("platform", platform);
    if (value === "live_square") next.set("creator_scene", value);
    setSearch(next);
  };
  const items = library.data?.pages.flatMap((page) => page.items) ?? [];
  return <div className="page-wrap creator-library-page">
    <PageHeader
      eyebrow="CREATOR LIBRARY"
      title="达人库"
      description={live
        ? `${platformLabel[platform]}直播达人资料；直播数据与短视频数据独立存储、独立更新，空值不显示为 0。`
        : juxing
          ? "独立于任务结果的磁力聚星当前达人资料；字段、单位与统计窗口保持聚星平台原始口径。"
          : "独立于任务结果的巨量星图当前达人资料；所有商业和表现指标保持平台原始口径。"}
    />
    <section className="panel library-filters">
      <div className="panel-heading"><div><h2>筛选与排序</h2><p>缺失数据仍保留；数值筛选仅作用于已成功采集的原始值。</p></div><label className="library-check"><input type="checkbox" checked={search.get("complete_only") === "true"} onChange={(event) => setFilter("complete_only", event.target.checked ? "true" : "")} />仅看数据完整</label></div>
      <div className="library-filter-grid">
        <label>平台<select aria-label="达人库平台" value={platform} onChange={(event) => setPlatform(event.target.value as "douyin_xingtu" | "kuaishou_juxing")}><option value="douyin_xingtu">巨量星图</option><option value="kuaishou_juxing">磁力聚星</option></select></label>
        <label>业务数据<select aria-label="达人库业务数据" value={scene} onChange={(event) => setScene(event.target.value as CreatorScene)}><option value="video_square">短视频</option><option value="live_square">直播</option></select></label>
        {!juxing && !live && <label>行业<input aria-label="按行业筛选" value={search.get("industry") ?? ""} onChange={(event) => setFilter("industry", event.target.value)} placeholder="例如：食品饮料" /></label>}
        {!juxing && !live && <label>达人类型<input aria-label="按达人类型筛选" value={search.get("creator_type") ?? ""} onChange={(event) => setFilter("creator_type", event.target.value)} placeholder="例如：生活" /></label>}
        <label>省份<input aria-label="按省份筛选" value={search.get("province") ?? ""} onChange={(event) => setFilter("province", event.target.value)} placeholder="例如：北京市" /></label>
        <label>城市<input aria-label="按城市筛选" value={search.get("city") ?? ""} onChange={(event) => setFilter("city", event.target.value)} placeholder="例如：朝阳区" /></label>
        <label>粉丝数下限<input type="number" min="0" value={search.get("followers_min") ?? ""} onChange={(event) => setFilter("followers_min", event.target.value)} /></label>
        <label>粉丝数上限<input type="number" min="0" value={search.get("followers_max") ?? ""} onChange={(event) => setFilter("followers_max", event.target.value)} /></label>
        {!juxing && !live && <label>互动原始值下限<input type="number" min="0" value={search.get("interaction_min") ?? ""} onChange={(event) => setFilter("interaction_min", event.target.value)} /></label>}
        {!juxing && !live && <label>完播原始值下限<input type="number" min="0" value={search.get("completion_min") ?? ""} onChange={(event) => setFilter("completion_min", event.target.value)} /></label>}
        {!juxing && !live && <label>预期 CPM 下限<input type="number" min="0" value={search.get("expected_cpm_min") ?? ""} onChange={(event) => setFilter("expected_cpm_min", event.target.value)} /></label>}
        {!juxing && !live && <label>预期 CPE 下限<input type="number" min="0" value={search.get("expected_cpe_min") ?? ""} onChange={(event) => setFilter("expected_cpe_min", event.target.value)} /></label>}
        {!juxing && !live && <label>合作形式<input aria-label="按合作形式筛选" value={search.get("cooperation_form") ?? ""} onChange={(event) => setFilter("cooperation_form", event.target.value)} placeholder="例如：植入视频" /></label>}
        <label>排序<select aria-label="达人库排序" value={search.get("sort") ?? "updated_at"} onChange={(event) => setFilter("sort", event.target.value)}><option value="updated_at">最近更新时间</option><option value="followers">粉丝数</option>{!juxing && !live && <><option value="monthly_growth">月涨粉原始值</option><option value="interaction">互动原始值</option><option value="completion">完播原始值</option><option value="expected_cpm">预期 CPM 原始值</option><option value="expected_cpe">预期 CPE 原始值</option></>}</select></label>
      </div>
    </section>
    <section className="panel library-results"><div className="panel-heading"><div><h2>{live ? `${platformLabel[platform]}直播达人` : juxing ? "磁力聚星达人" : "巨量星图达人"}</h2><p>{live ? "直播资料单独读取；默认按最近更新时间倒序，指标为平台原生口径。" : juxing ? "默认按最近更新时间倒序；聚星专属指标保留原单位与统计窗口，不与星图指标等同。" : "默认按最近更新时间倒序；“原始值”不代表统一百分比、币种或跨平台指标。"}</p></div><span>{items.length} 位已加载</span></div>
      {library.isLoading ? <SkeletonRows rows={7} /> : library.isError ? <ErrorState error={library.error} retry={() => library.refetch()} /> : !items.length ? <EmptyState title="暂无匹配达人" description={live ? "该平台当前没有已发布的直播达人资料；系统不会用空值补造数据。" : juxing ? "该平台当前没有已发布的聚星达人资料；系统不会用空值补造数据。" : "调整筛选条件后重试；系统不会用空值补造数据。"} /> : <div className="library-rows">{items.map((creator) => <CreatorLibraryRow key={creator.creator_id} creator={creator} />)}</div>}
      {library.hasNextPage && <div className="pagination"><button className="button secondary" disabled={library.isFetchingNextPage} onClick={() => library.fetchNextPage()}>{library.isFetchingNextPage ? "正在读取" : "查看更多达人"}<ArrowRight size={16} /></button></div>}
    </section>
  </div>;
}

function CreatorLibraryRow({ creator }: { creator: CreatorLibrarySummary }) {
  const complete = creator.profile_complete && creator.pipeline_complete;
  const juxing = creator.platform === "kuaishou_juxing";
  const live = creator.creator_scene === "live_square";
  const liveMetrics = liveMetricList(creator.platform, undefined, creator.live_metrics).filter((item) => item.status === "COLLECTED").slice(0, 3);
  return <Link className="library-row" to={live ? `/creators/${creator.creator_id}/live` : `/creators/${creator.creator_id}`}>
    <div className="creator-avatar">{creator.avatar_uri ? <img src={creator.avatar_uri} alt="" /> : <UserRound size={20} />}</div>
    <div className="library-identity">
      <strong>{creator.display_name || "未提供昵称"}</strong>
      {/* Xingtu rows keep their original「达人类型 · 地区」line; juxing has no verified creator
          type taxonomy, so it states the platform instead of inventing one. */}
      <span>{live
        ? `${platformLabel[creator.platform]} · 直播 · ${creator.creator_type_label || creator.content_theme_labels[0] || "类型暂无数据"} · ${[creator.province, creator.city].filter(Boolean).join(" / ") || "地区暂无数据"}`
        : `${juxing ? "磁力聚星" : (creator.creator_type_label || "类型暂无数据")} · ${[creator.province, creator.city].filter(Boolean).join(" / ") || "地区暂无数据"}`}</span>
      <em>{juxing
        ? (creator.content_theme_labels.length ? creator.content_theme_labels.join(" / ") : "内容类型暂无数据")
        : (creator.industry_labels.length ? creator.industry_labels.join(" / ") : "行业暂无数据")}</em>
    </div>
    <div className="library-stat"><span>粉丝</span><strong>{numberText(creator.followers.value)}</strong></div>
    {live ? (
      <>
        {liveMetrics.map((metric) => <div className="library-stat" key={metric.key}><span>{metric.label}</span><strong>{metric.value}</strong></div>)}
        <div className="library-stat"><span>最近更新</span><strong>{creator.data_updated_at ? formatDate(creator.data_updated_at) : "暂无"}</strong></div>
      </>
    ) : juxing ? (
      <>
        <div className="library-stat"><span>月涨粉率</span><strong>{ratioMetric(creator.monthly_follower_growth_rate)}</strong></div>
        <div className="library-stat"><span>互动 / 完播</span><strong>{ratioMetric(creator.interaction_rate)} / {ratioMetric(creator.completion_rate)}</strong></div>
        <div className="library-stat"><span>播放中位数</span><strong>{numberText(creator.play_median.value)}</strong></div>
      </>
    ) : (
      <>
        <div className="library-stat"><span>月深度用户</span><strong>{rawMetric(creator.monthly_deep_users)}</strong></div>
        <div className="library-stat"><span>互动 / 完播原始值</span><strong>{rawMetric(creator.interaction_rate)} / {rawMetric(creator.completion_rate)}</strong></div>
        <div className="library-stat"><span>CPM / CPE 原始值</span><strong>{rawMetric(creator.expected_cpm_21_60)} / {rawMetric(creator.expected_cpe_21_60)}</strong></div>
      </>
    )}
    <div className={`library-quality ${complete ? "complete" : "incomplete"}`}><span>{complete ? "采集完整" : "数据不完整"}</span><small>{creator.data_updated_at ? formatDate(creator.data_updated_at) : "暂无更新时间"}</small></div><ChevronRight size={18} />
  </Link>;
}

export function CreatorLibraryDetailPage() {
  const { creatorId = "" } = useParams();
  const location = useLocation();
  const queryClient = useQueryClient();
  const scene: CreatorScene = location.pathname.endsWith("/live") ? "live_square" : "video_square";
  const live = scene === "live_square";
  const detail = useQuery({
    queryKey: ["creator-library", creatorId, scene],
    queryFn: () => api.creatorLibraryDetail(creatorId, scene),
  });
  const platform = detail.data?.platform ?? "douyin_xingtu";
  const juxing = platform === "kuaishou_juxing";
  // 聚星/直播没有星图报价/历史/精选/作品观测读模型：不发起这些只属于星图视频的请求。
  const quotes = useQuery({ queryKey: ["creator-library-quotes", creatorId], queryFn: () => api.creatorLibraryQuotes(creatorId), enabled: Boolean(detail.data) && !juxing && !live });
  const update = useQuery({
    queryKey: ["creator-update", creatorId, live ? "live" : "video"],
    queryFn: () => live ? api.creatorLiveUpdateStatus(creatorId) : api.creatorUpdateStatus(creatorId),
    enabled: Boolean(detail.data) && (live || !juxing),
    refetchInterval: (query) => (query.state.data?.in_flight_root_task_id ? 5_000 : false),
  });
  const requestUpdate = useMutation({
    mutationFn: () => live
      ? api.createCreatorLiveUpdate(creatorId, crypto.randomUUID())
      : api.createCreatorUpdate(creatorId, crypto.randomUUID()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["creator-update", creatorId] });
      void queryClient.invalidateQueries({ queryKey: ["creator-library", creatorId] });
    },
  });
  const contents = useFeaturedContent({ kind: "library", creatorId }, Boolean(detail.data) && !juxing && !live);
  const videos = useVideoObservations({ kind: "library", creatorId }, Boolean(detail.data) && !juxing && !live);
  if (detail.isLoading) return <div className="page-wrap"><LoadingState label="正在读取达人库资料" /></div>;
  if (detail.isError || !detail.data) return <div className="page-wrap"><ErrorState error={detail.error} retry={() => detail.refetch()} /></div>;
  const creator = detail.data;
  if (live) {
    const liveActions = <div className="creator-update-actions">
      <button className="button primary" disabled={Boolean(update.data?.in_flight_root_task_id) || requestUpdate.isPending} onClick={() => requestUpdate.mutate()}>
        {requestUpdate.isPending ? <><LoaderCircle className="spin" size={16} />正在提交</> : update.data?.in_flight_root_task_id ? <><Clock3 size={16} />更新进行中</> : <><RefreshCcw size={16} />手动更新直播资料</>}
      </button>
      {update.data?.in_flight_root_task_id && <Link className="origin-link" to={`/tasks/${update.data.in_flight_root_task_id}`}>查看更新任务<ChevronRight size={14} /></Link>}
      {update.data?.last_success_at && <span>最近成功更新 {formatDate(update.data.last_success_at)}</span>}
      {update.data?.last_write_at && update.data.last_write_at !== update.data.last_success_at && <span>最近写入 {formatDate(update.data.last_write_at)}</span>}
      {update.data?.last_failure_reason && <span>最近一次未完成：{update.data.last_failure_reason}</span>}
      {requestUpdate.isError && <span className="form-error">{friendlyError(requestUpdate.error)}</span>}
    </div>;
    const hasVideo = (creator.available_scenes ?? []).includes("video_square");
    return <LiveCreatorDetailView
      platform={platform}
      creatorId={creator.creator_id}
      platformCreatorId={creator.platform_creator_id}
      displayName={creator.display_name}
      payload={creator.profile_payload}
      liveMetrics={creator.live_metrics}
      observedAt={creator.data_updated_at}
      backTo="/creators?creator_scene=live_square"
      backLabel="返回达人库"
      scopeLabel="当前直播资料"
      actions={liveActions}
      availableScenes={creator.available_scenes}
      videoHref={hasVideo ? `/creators/${creator.creator_id}` : undefined}
      liveHref={`/creators/${creator.creator_id}/live`}
    />;
  }
  const quoteRows = quotes.data ?? [];
  const seenForms = new Set<string>();
  const currentQuotes = quoteRows.filter((quote) => {
    const form = quote.cooperation_form || "__unmarked__";
    if (seenForms.has(form)) return false;
    seenForms.add(form);
    return true;
  });
  const quoteHistory = quoteRows.filter((quote) => !currentQuotes.includes(quote));
  const inFlight = Boolean(update.data?.in_flight_root_task_id);
  const updateActions = <div className="creator-update-actions">
    <button className="button primary" disabled={inFlight || requestUpdate.isPending} onClick={() => requestUpdate.mutate()}>
      {requestUpdate.isPending ? <><LoaderCircle className="spin" size={16} />正在提交</> : inFlight ? <><Clock3 size={16} />更新进行中</> : <><RefreshCcw size={16} />手动更新</>}
    </button>
    {update.data?.in_flight_root_task_id && <Link className="origin-link" to={`/tasks/${update.data.in_flight_root_task_id}`}>查看更新任务<ChevronRight size={14} /></Link>}
    {update.data?.last_success_at && <span>最近成功更新 {formatDate(update.data.last_success_at)}</span>}
    {update.data?.last_write_at && update.data.last_write_at !== update.data.last_success_at && <span>最近写入 {formatDate(update.data.last_write_at)}</span>}
    {update.data?.next_due_at && <span>下次定时更新 {formatDate(update.data.next_due_at)}</span>}
    {update.data?.last_failure_reason && <span>最近一次未完成：{update.data.last_failure_reason}</span>}
    {requestUpdate.isError && <span className="form-error">{friendlyError(requestUpdate.error)}</span>}
  </div>;
  return <CreatorDetailView
    creator={creator}
    profilePayload={creator.profile_payload || {}}
    platform={platform}
    backTo="/creators"
    backLabel="返回达人库"
    scopeLabel="当前达人资料"
    badgeLabel={completeLabel(creator)}
    badgeTone={creator.profile_complete && creator.pipeline_complete ? "published" : "draft"}
    contents={juxing ? undefined : contents}
    videos={juxing ? undefined : videos}
    actions={juxing ? undefined : updateActions}
    historyChapter={juxing ? undefined : <div className="profile-sections">
      <section className="panel library-detail-panel"><div className="panel-heading"><div><h2>报价历史</h2><p>同一合作形式的较早观察，保留原始报价与观测时间。</p></div><span>{quoteHistory.length} 条</span></div>{quotes.isLoading ? <SkeletonRows rows={3} /> : quotes.isError ? <ErrorState error={quotes.error} retry={() => quotes.refetch()} /> : <div className="quote-list">{quoteHistory.length ? quoteHistory.map((quote) => <div key={`${quote.snapshot_id}-${quote.position}`}><strong>{quote.cooperation_form || "未标记合作形式"}</strong><span>{quote.settlement_description || "结算说明暂无数据"}</span><b>{quote.price_raw === null ? "暂无报价" : String(quote.price_raw)}</b><small>{formatDate(quote.observed_at)}</small></div>) : <p className="muted">暂无更早报价观察。</p>}</div>}</section>
    </div>}
  />;
}

function secondsLabel(value: string | null) {
  if (!value) return "—";
  const seconds = Math.max(0, Math.floor((new Date(value).getTime() - Date.now()) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function unitLabel(unit: ExecutionUnit) {
  if (unit.takeover_state === "ACTIVE") return "人工接管中";
  if (unit.takeover_state === "VERIFYING") return "正在校验验证结果";
  if (unit.verification_state === "ACCOUNT_SELECTION_REQUIRED") return "需要选择子账号";
  if (unit.verification_state) return "等待人工验证";
  if (unit.browser_status === "QUARANTINED") return "已隔离";
  if (unit.browser_status === "SUSPECTED_OFFLINE") return "疑似失联";
  if (unit.worker_status === "DUPLICATE") return "Worker 重复运行";
  if (unit.worker_status === "OFFLINE") return "Worker 离线";
  if (unit.mode === "collect") return "采集中";
  return unit.state === "READY" ? "空闲可用" : unit.state;
}

function TakeoverWorkspace({ takeover, close }: { takeover: BrowserTakeover; close: () => void }) {
  const queryClient = useQueryClient();
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackReason, setFeedbackReason] = useState("PLATFORM_SECURITY_CHALLENGE");
  const complete = useMutation({
    mutationFn: () => api.completeTakeover(takeover.takeover_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["takeover", takeover.takeover_id] }),
  });
  const reappearance = useMutation({
    mutationFn: (reason: string) => api.takeoverReappearance(takeover.takeover_id, reason),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["takeover", takeover.takeover_id] }),
  });
  const release = useMutation({ mutationFn: () => api.releaseTakeover(takeover.takeover_id), onSuccess: close });
  const actionable = takeover.state === "ACTIVE";
  return <div className="takeover-overlay" role="dialog" aria-modal="true" aria-label="人工浏览器接管">
    <section className="takeover-workspace">
      <header><div><button className="icon-button" aria-label="关闭接管工作区" onClick={close}><X size={18} /></button><span className="eyebrow">ORIGINAL BROWSER CONTROL</span><h2>{takeover.unit_id} · {takeover.state === "ACTIVE" ? "人工验证中" : "验证状态同步中"}</h2></div><strong>剩余 {secondsLabel(takeover.expires_at)}</strong></header>
      <div className="takeover-viewer">
        {takeover.state === "REQUESTED" && <LoadingState label="正在确认原浏览器实例仍在线" />}
        {takeover.state === "ACTIVE" && takeover.viewer_url && <iframe title="原 Chromium 浏览器" src={takeover.viewer_url} allow="clipboard-read; clipboard-write" />}
        {takeover.state === "ACTIVE" && takeover.access_mode === "LOCAL_WINDOW" && <div className="state-panel"><MonitorCog /><strong>请切换到本机原 Chrome 窗口</strong><span>{takeover.operator_message || "系统已暂停自动操作；请在已经打开的执行单元 Chrome 中完成人工验证。"}</span></div>}
        {takeover.state === "ACTIVE" && takeover.access_mode === "REMOTE_VIEWER" && !takeover.viewer_url && <div className="state-panel"><MonitorCog /><strong>远程浏览器暂不可用</strong><span>Worker 已确认接管，但远程查看器尚未就绪。请稍后重试，不要启动第二个浏览器。</span></div>}
        {takeover.state === "VERIFYING" && <LoadingState label="正在检查验证、账号与受保护业务页面" />}
        {["FAILED", "EXPIRED", "RELEASED", "RESUMED"].includes(takeover.state) && <div className="state-panel"><ShieldCheck /><strong>{takeover.state === "RESUMED" ? "验证通过，任务已恢复" : "本次接管已结束"}</strong><span>{takeover.failure_reason || "请返回执行单元查看最新状态。"}</span></div>}
      </div>
      <footer>
        <div><strong>系统已暂停自动页面检测与采集操作。</strong><span>可在当前原浏览器内手动检查最多 3 位未完成达人；系统不会自动打开或采集它们。</span></div>
        <div className="takeover-actions">
          <button className="button ghost" disabled={!actionable || reappearance.isPending} onClick={() => setFeedbackOpen(true)}><TriangleAlert size={16} />仍有验证/无法完成</button>
          <button className="button secondary" disabled={!actionable || release.isPending} onClick={() => release.mutate()}>放弃接管</button>
          <button className="button primary" disabled={!actionable || complete.isPending} onClick={() => complete.mutate()}><Check size={16} />我已完成验证/选择</button>
        </div>
      </footer>
      {feedbackOpen && <div className="takeover-feedback" role="group" aria-label="无法完成原因"><label>当前情况<select value={feedbackReason} onChange={(event) => setFeedbackReason(event.target.value)}><option value="PLATFORM_SECURITY_CHALLENGE">滑块或交互验证再次出现</option><option value="ACCOUNT_LOGIN_REQUIRED">已跳转登录页</option><option value="ACCOUNT_MISMATCH">当前账号不正确</option><option value="NETWORK_OR_PROTECTED_PAGE_UNAVAILABLE">网络或页面无法访问</option><option value="HUMAN_CANNOT_COMPLETE">人工暂时无法完成</option></select></label><button className="button secondary" onClick={() => setFeedbackOpen(false)}>取消</button><button className="button primary" disabled={reappearance.isPending} onClick={() => { reappearance.mutate(feedbackReason); setFeedbackOpen(false); }}>提交状态</button></div>}
      {takeover.manual_probe_creators.length > 0 && <div className="probe-note"><MousePointer2 size={15} />建议人工核验：{takeover.manual_probe_creators.map((item) => item.platform_creator_id).join("、")}</div>}
    </section>
  </div>;
}

export function ExecutionUnitsPage() {
  const queryClient = useQueryClient();
  const [takeoverId, setTakeoverId] = useState<string | null>(null);
  const units = useQuery({ queryKey: ["execution-units"], queryFn: api.executionUnits, refetchInterval: 5_000 });
  const events = useQuery({ queryKey: ["verification-events"], queryFn: api.verificationEvents, refetchInterval: 5_000 });
  const takeover = useQuery({
    queryKey: ["takeover", takeoverId], queryFn: () => api.takeover(takeoverId || ""), enabled: Boolean(takeoverId),
    refetchInterval: (query) => ["RESUMED", "FAILED", "EXPIRED", "RELEASED"].includes(query.state.data?.state || "") ? false : 2_000,
  });
  const request = useMutation({
    mutationFn: (unitId: string) => api.requestTakeover(unitId),
    onSuccess: (data) => { setTakeoverId(data.takeover_id); queryClient.invalidateQueries({ queryKey: ["execution-units"] }); },
  });
  if (units.isLoading) return <div className="page-wrap"><LoadingState label="正在读取执行单元" /></div>;
  if (units.isError || !units.data) return <div className="page-wrap"><ErrorState error={units.error} retry={() => units.refetch()} /></div>;
  const waiting = events.data?.filter((event) => ["OPEN", "ACKNOWLEDGED"].includes(event.state)) ?? [];
  const nearingDeadline = waiting
    .filter((event) => event.remaining_seconds <= 300)
    .sort((left, right) => left.remaining_seconds - right.remaining_seconds)[0];
  return <div className="page-wrap">
    <PageHeader eyebrow="RESOURCE CONTROL" title="执行单元管理" description="查看采集资源状态，并在平台要求时接管原浏览器完成人工验证。" />
    {waiting.length > 0 && <section className="verification-alert"><TriangleAlert size={20} /><div><strong>{waiting.length} 个执行单元需要人工验证</strong><span>{waiting.map((event) => `${event.unit_id}（${event.reason === "ACCOUNT_SELECTION_REQUIRED" ? "需要选择子账号 cpg果汁（60821564）" : "需要人工验证"}，剩余 ${Math.floor(event.remaining_seconds / 60)} 分钟）`).join(" · ")}</span>{nearingDeadline && <em>当前验证等待窗口剩余 {Math.floor(nearingDeadline.remaining_seconds / 60)}:{String(nearingDeadline.remaining_seconds % 60).padStart(2, "0")}。若平台再次出现验证，请在原浏览器内完成后重新提交校验。</em>}</div></section>}
    <section className="unit-summary-grid">
      <div className="panel"><span>可用单元</span><strong>{units.data.filter((unit) => unit.state === "READY" && unit.worker_status === "ONLINE").length}</strong></div>
      <div className="panel"><span>采集中</span><strong>{units.data.filter((unit) => unit.mode === "collect").length}</strong></div>
      <div className="panel warning"><span>待人工验证</span><strong>{waiting.length}</strong></div>
      <div className="panel danger"><span>隔离/异常</span><strong>{units.data.filter((unit) => ["QUARANTINED", "SUSPECTED_OFFLINE"].includes(unit.browser_status) || ["OFFLINE", "DUPLICATE"].includes(unit.worker_status)).length}</strong></div>
    </section>
    <section className="panel unit-table-wrap"><table className="unit-table"><thead><tr><th>执行单元</th><th>运行状态</th><th>绑定账号/线路</th><th>当前任务</th><th>Worker</th><th>浏览器</th><th>验证</th><th>最近心跳</th><th /></tr></thead><tbody>{units.data.map((unit) => <tr key={unit.unit_id}><td><strong>{unit.unit_id}</strong><small>{(unit.platforms ?? [unit.platform]).map((platform) => platformLabel[platform]).join(" / ")}</small></td><td><b>{unitLabel(unit)}</b><small>{unit.actionable_reason || "—"}</small></td><td><span>{unit.account_label}</span><small>{unit.line_label}</small></td><td>{unit.current_root_task_id ? <Link to={`/tasks/${unit.current_root_task_id}`}>{shortId(unit.current_root_task_id)}</Link> : "—"}</td><td><b>{unit.worker_status}</b><small>{unit.worker_instances} 实例 · {formatDate(unit.worker_last_heartbeat_at)}</small></td><td>{unit.browser_status}</td><td>{unit.verification_state ? <><b>{unit.takeover_state || unit.verification_state}</b><small>{secondsLabel(unit.verification_deadline_at)}</small></> : "正常"}</td><td>{formatDate(unit.last_heartbeat_at)}</td><td>{unit.verification_state ? <button className="button primary" disabled={request.isPending || unit.takeover_state === "VERIFYING"} onClick={() => request.mutate(unit.unit_id)}>{unit.takeover_state === "ACTIVE" ? "重新进入" : unit.takeover_state === "REQUESTED" ? "查看接管" : unit.takeover_state === "VERIFYING" ? "系统校验中" : "接管浏览器"}</button> : <button className="button ghost" disabled>查看</button>}</td></tr>)}</tbody></table></section>
    {request.isError && <div className="form-error" role="alert"><AlertCircle size={16} />{friendlyError(request.error)}</div>}
    {takeover.data && <TakeoverWorkspace takeover={takeover.data} close={() => { setTakeoverId(null); queryClient.invalidateQueries({ queryKey: ["execution-units"] }); }} />}
  </div>;
}
