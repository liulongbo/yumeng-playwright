import { useMemo, useState } from "react";
import { BarChart3, Database, Info, TrendingUp } from "lucide-react";
import { fieldByKey } from "./snapshotCreator";

type RecordValue = Record<string, unknown>;

function record(value: unknown): RecordValue { return value && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {}; }
function fields(payload: RecordValue, module: string): RecordValue[] {
  const entry = record(record(payload.modules)[module]);
  return Array.isArray(entry.fields) ? entry.fields.filter((item): item is RecordValue => Boolean(item && typeof item === "object")) : [];
}
function label(field: RecordValue) { return typeof field.name === "string" ? field.name : String(field.field_key || "平台字段"); }
function statusText(status: unknown) {
  return ({ COLLECTED: "已采集", NO_DATA: "平台暂无数据", NOT_ATTEMPTED: "本次未采集", NO_PERMISSION: "无访问权限", FAILED: "采集失败" } as Record<string, string>)[String(status)] || "暂无数据";
}
function scalar(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return value.toLocaleString("zh-CN");
  if (typeof value === "string") return value;
  const item = record(value);
  if ("amount" in item) return scalar(item.amount);
  if ("data" in item) return scalar(item.data);
  if (Array.isArray(value)) return value.length ? `${value.length} 条记录` : "暂无记录";
  return Object.entries(item).slice(0, 3).map(([key, child]) => `${key}：${scalar(child)}`).join(" · ") || "—";
}
function data(field: RecordValue) { const value = record(field.value); return value.data ?? field.value; }

function FieldFacts({ payload, module, title }: { payload: RecordValue; module: string; title: string }) {
  const values = fields(payload, module);
  if (!values.length) return <section className="profile-panel"><h3>{title}</h3><p className="muted">本次没有可读取的模块数据。</p></section>;
  return <section className="profile-panel"><div className="profile-heading"><h3>{title}</h3><span>{values.filter((field) => field.status === "COLLECTED").length}/{values.length} 已采集</span></div><dl className="profile-facts">{values.map((field) => <div key={String(field.field_key)}><dt>{label(field)}<small>{field.period_label ? ` · ${String(field.period_label)}` : ""}</small></dt><dd><span>{field.status === "COLLECTED" ? scalar(data(field)) : statusText(field.status)}</span>{field.status !== "COLLECTED" && <em>{statusText(field.status)}</em>}</dd></div>)}</dl></section>;
}

function Series({ title, field }: { title: string; field: RecordValue | null }) {
  const points = Array.isArray(data(field || {})) ? data(field || {}) as RecordValue[] : [];
  const key = points.some((point) => "fans_cnt" in point) ? "fans_cnt" : "value";
  const numbers = points.map((point) => Number(point[key])).filter(Number.isFinite);
  const max = Math.max(...numbers, 1);
  return <section className="profile-panel chart-panel"><div className="profile-heading"><div><h3>{title}</h3><p>本次采集返回的星图平台内置趋势，不是系统采集历史。</p></div><TrendingUp size={18} /></div>{points.length ? <div className="mini-bars" aria-label={title}>{points.map((point, index) => <div key={`${String(point.date)}-${index}`} title={`${String(point.date || index + 1)}：${scalar(point[key])}`}><i style={{ height: `${Math.max(4, Number(point[key]) / max * 100)}%` }} /><small>{index === 0 || index === points.length - 1 ? String(point.date || "") : ""}</small></div>)}</div> : <p className="muted">{statusText(field?.status)}</p>}</section>;
}

function Videos({ payload }: { payload: RecordValue }) {
  const [kind, setKind] = useState<"recent_video_performance" | "recent_xingtu_video_performance">("recent_video_performance");
  const [metric, setMetric] = useState<"play" | "like" | "comment" | "share">("play");
  const source = fieldByKey(payload, kind);
  const items = Array.isArray(data(source || {})) ? data(source || {}) as RecordValue[] : [];
  const max = Math.max(...items.map((item) => Number(item[metric]) || 0), 1);
  return <section className="profile-panel wide-profile-panel" id="content"><div className="profile-heading"><div><h3>内容与视频表现</h3><p>每根柱与下方同一视频记录关联；切换不会混合不同指标。</p></div><BarChart3 size={18} /></div><div className="profile-controls"><div><button className={kind === "recent_video_performance" ? "active" : ""} onClick={() => setKind("recent_video_performance")}>最新视频</button><button className={kind === "recent_xingtu_video_performance" ? "active" : ""} onClick={() => setKind("recent_xingtu_video_performance")}>最新星图视频</button></div><div>{(["play", "like", "comment", "share"] as const).map((value) => <button key={value} className={metric === value ? "active" : ""} onClick={() => setMetric(value)}>{{ play: "播放", like: "点赞", comment: "评论", share: "分享" }[value]}</button>)}</div></div>{items.length ? <><div className="video-bars">{items.map((item, index) => <div key={String(item.item_id || item.video_id || index)} title={`${String(item.title || item.item_title || `视频 ${index + 1}`)}：${scalar(item[metric])}`}><i style={{ height: `${Math.max(3, (Number(item[metric]) || 0) / max * 100)}%` }} /><span>{index + 1}</span></div>)}</div><div className="video-table"><div className="video-head"><span>视频</span><span>发布时间</span><span>时长</span><span>播放</span><span>赞评转</span></div>{items.map((item, index) => <div key={String(item.item_id || item.video_id || index)}><strong>{String(item.title || item.item_title || `视频 ${index + 1}`)}</strong><span>{String(item.create_time || item.item_date || "—")}</span><span>{scalar(item.duration || item.duration_min)}</span><span>{scalar(item.play)}</span><span>{`${scalar(item.like)} / ${scalar(item.comment)} / ${scalar(item.share)}`}</span></div>)}</div></> : <p className="muted">{statusText(source?.status)}</p>}</section>;
}

function Audience({ payload }: { payload: RecordValue }) {
  const field = fieldByKey(payload, "audience_distributions");
  const groups = Array.isArray(data(field || {})) ? data(field || {}) as RecordValue[] : [];
  const [active, setActive] = useState(0);
  const group = groups[active] || {};
  const list = Array.isArray(group.distribution_list) ? group.distribution_list as RecordValue[] : [];
  const max = Math.max(...list.map((item) => Number(item.distribution_value) || 0), 1);
  return <section className="profile-panel wide-profile-panel" id="audience"><div className="profile-heading"><div><h3>连接用户画像</h3><p>平台画像更新时间：{scalar(fieldByKey(payload, "audience_last_updated_at")?.value)}</p></div></div>{groups.length ? <><div className="profile-controls">{groups.map((item, index) => <button key={String(item.type || index)} className={active === index ? "active" : ""} onClick={() => setActive(index)}>{String(item.type_display || item.type || `画像 ${index + 1}`)}</button>)}</div><div className="distribution-list">{list.map((item, index) => <div key={String(item.distribution_key || index)}><span>{String(item.distribution_key || "未命名")}</span><i><b style={{ width: `${Math.max(2, Number(item.distribution_value) / max * 100)}%` }} /></i><strong>{scalar(item.distribution_value)}</strong></div>)}</div></> : <p className="muted">{statusText(field?.status)}</p>}</section>;
}

function Funnel({ payload }: { payload: RecordValue }) {
  const field = fieldByKey(payload, "connection_funnel"); const value = record(data(field || {}));
  return <section className="profile-panel"><div className="profile-heading"><div><h3>连接用户阶段结构</h3><p>阶段业务含义尚未确认，按平台阶段码原样展示。</p></div></div><div className="stage-list">{Object.keys(value).sort().map((key) => { const item = record(value[key]); return <div key={key}><b>平台阶段 {key}</b><span>{scalar(item.value)}</span><small>相对比率 {scalar(item.relative_ratio)}</small></div>; })}</div>{!Object.keys(value).length && <p className="muted">{statusText(field?.status)}</p>}</section>;
}

export function ProfilePresentation({ payload }: { payload: RecordValue }) {
  const profile = useMemo(() => payload || {}, [payload]);
  return <div className="profile-sections">
    <div className="profile-grid" id="overview"><FieldFacts payload={profile} module="basic" title="完整基础资料" /><FieldFacts payload={profile} module="spread" title="商业传播表现" /></div>
    <Videos payload={profile} />
    <div className="profile-grid"><Series title="近 30 日连接用户总量" field={fieldByKey(profile, "fans_daily_trend")} /><Series title="近 30 日连接用户增量" field={fieldByKey(profile, "fans_daily_delta")} /><Series title="近 30 日连接用户趋势" field={fieldByKey(profile, "connection_daily_trend")} /><Funnel payload={profile} /></div>
    <Audience payload={profile} />
    <div className="profile-grid" id="seeding"><FieldFacts payload={profile} module="seeding" title="种草表现" /><FieldFacts payload={profile} module="conversion" title="转化能力" /></div>
    <div className="profile-grid" id="fulfillment"><FieldFacts payload={profile} module="fulfillment" title="履约与合作" /></div>
    <div className="profile-grid" id="quotes"><FieldFacts payload={profile} module="commercial" title="商业合作资料" /></div>
  </div>;
}

export function ProfileProvenance({ modules, fields }: { modules: Record<string, string | null>; fields: Record<string, unknown> }) {
  return <details className="profile-provenance"><summary><Database size={15} />查看数据质量与字段来源</summary><p><Info size={14} />字段显示的是平台原始口径；观察时间、周期与状态以来源数据为准。</p><div className="module-statuses">{Object.entries(modules).map(([key, value]) => <span key={key}>{key}：{statusText(value)}</span>)}</div><dl>{Object.entries(fields).map(([key, value]) => { const source = record(value); return <div key={key}><dt>{key}</dt><dd>{statusText(source.status)}{source.observed_at ? ` · ${String(source.observed_at)}` : ""}{source.period_label ? ` · ${String(source.period_label)}` : ""}</dd></div>; })}</dl></details>;
}
