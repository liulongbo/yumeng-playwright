import { Link } from "react-router-dom";
import { ArrowLeft, ExternalLink, RefreshCcw, UserRound } from "lucide-react";
import type { CreatorScene, LiveMetricEnvelope } from "./types";
import { formatDate } from "./status";

const platformLabel = { douyin_xingtu: "巨量星图", kuaishou_juxing: "磁力聚星" } as const;

const labels: Record<string, Record<string, string>> = {
  douyin_xingtu: {
    "live.room_cnt": "近期直播场次",
    "live.watch_ucnt_avg": "平均观看人数",
    "live.watch_cnt_avg": "平均观看人次",
    "live.acu": "ACU",
    "live.pcu": "PCU",
    "live.fans_watch_rate": "粉丝观看占比",
    "live.follow_ucnt_avg": "场均涨粉数",
    "live.comment_rate_avg": "场均评论率",
    "live.like_rate_avg": "场均点赞率",
    "live.watch_duration_avg": "平均看播时长",
    "live.interact_rate_avg": "场均互动率",
    "live.acu_precede_percent": "同粉段 ACU 排名",
    "live.ecom_product_num": "带货商品数",
    "live.ecom_avg_gmv_range": "场均 GMV",
    "live.ecom_avg_price_range": "带货商品客单价",
    "live.ecom_avg_gpm_range": "GPM",
  },
  kuaishou_juxing: {
    "live.expect_viewer": "预期观看人数",
    "live.max_online": "最高在线人数",
    "live.expect_cpm": "预期 CPM",
    "live.weekly_sessions": "周均直播场次",
    "live.avg_people": "平均观看人数",
    "live.avg_like": "场均点赞",
    "live.week_release": "直播周发布",
    "live.interaction_rate": "直播互动率",
    "live.quote_hour": "直播按小时报价",
    "live.quote_day": "直播按天报价",
    "live.quote_goods": "直播按商品报价",
    "live.commerce_sessions": "带货直播场次",
    "live.commerce_watch_median": "观看人数中位数",
    "live.commerce_max_online_median": "最高在线人数中位数",
    "live.commerce_goods": "带货商品数量",
  },
};

const groups: Record<string, string[][]> = {
  douyin_xingtu: [
    ["live.room_cnt", "live.watch_ucnt_avg", "live.watch_cnt_avg", "live.acu", "live.pcu"],
    ["live.fans_watch_rate", "live.follow_ucnt_avg", "live.comment_rate_avg", "live.like_rate_avg", "live.watch_duration_avg"],
    ["live.ecom_product_num", "live.ecom_avg_gmv_range", "live.ecom_avg_price_range", "live.ecom_avg_gpm_range"],
  ],
  kuaishou_juxing: [
    ["live.expect_viewer", "live.max_online", "live.expect_cpm", "live.weekly_sessions", "live.interaction_rate"],
    ["live.avg_people", "live.avg_like", "live.week_release"],
    ["live.commerce_sessions", "live.commerce_watch_median", "live.commerce_max_online_median", "live.commerce_goods"],
    ["live.quote_hour", "live.quote_day", "live.quote_goods"],
  ],
};

function flatten(payload: Record<string, unknown> | undefined): Record<string, LiveMetricEnvelope> {
  const out: Record<string, LiveMetricEnvelope> = {};
  const modules = payload?.modules;
  if (!modules || typeof modules !== "object") return out;
  for (const module of Object.values(modules as Record<string, unknown>)) {
    const fields = (module as { fields?: unknown })?.fields;
    if (!Array.isArray(fields)) continue;
    for (const item of fields) {
      if (item && typeof item === "object") {
        const field = item as LiveMetricEnvelope & { field_key?: string };
        if (field.field_key) out[field.field_key] = field;
      }
    }
  }
  return out;
}

function amount(value: unknown): number | null {
  if (value && typeof value === "object" && "amount" in value) {
    const raw = (value as { amount?: unknown }).amount;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function display(field: LiveMetricEnvelope | undefined): string {
  if (!field || field.status === "NO_DATA" || field.status === "NO_PERMISSION" || field.status === "NOT_PROVIDED") return "暂无数据";
  if (field.status === "FAILED" || field.status === "NOT_ATTEMPTED") return "采集失败";
  const numeric = amount(field.value);
  if (field.unit === "ratio" && numeric !== null) return `${(numeric * 100).toFixed(2)}%`;
  if (field.unit === "second" && numeric !== null) {
    const seconds = Math.max(0, Math.round(numeric));
    return `${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, "0")}秒`;
  }
  if (field.unit === "yuan" && numeric !== null) return `¥${numeric.toLocaleString("zh-CN")}`;
  if (numeric !== null && field.unit === "count") return numeric.toLocaleString("zh-CN");
  return String(field.raw_value ?? field.value ?? "暂无数据");
}

export function payloadDisplayName(payload: Record<string, unknown> | undefined, fallback: string): string {
  const field = flatten(payload).nickname;
  if (!field) return fallback;
  const value = field.value;
  return typeof value === "string" && value.trim() ? value : fallback;
}

export function liveMetricList(
  platform: "douyin_xingtu" | "kuaishou_juxing",
  payload: Record<string, unknown> | undefined,
  liveMetrics?: Record<string, LiveMetricEnvelope>,
): Array<{ key: string; label: string; value: string; period: string | null; status: string }> {
  const flat = { ...flatten(payload), ...(liveMetrics ?? {}) };
  return (groups[platform] ?? []).flat().map((key) => {
    const field = flat[key];
    return {
      key,
      label: labels[platform]?.[key] ?? key,
      value: display(field),
      period: field?.period_label ?? null,
      status: field?.status ?? "NOT_AVAILABLE",
    };
  });
}

export function LiveCreatorDetailView({
  platform,
  creatorId,
  platformCreatorId,
  displayName,
  payload,
  liveMetrics,
  observedAt,
  backTo,
  backLabel,
  scopeLabel,
  actions,
  availableScenes,
  videoHref,
  liveHref,
}: {
  platform: "douyin_xingtu" | "kuaishou_juxing";
  creatorId: string;
  platformCreatorId: string;
  displayName?: string | null;
  payload?: Record<string, unknown>;
  liveMetrics?: Record<string, LiveMetricEnvelope>;
  observedAt?: string | null;
  backTo: string;
  backLabel: string;
  scopeLabel: string;
  actions?: React.ReactNode;
  availableScenes?: CreatorScene[];
  videoHref?: string;
  liveHref?: string;
}) {
  const metrics = liveMetricList(platform, payload, liveMetrics);
  return <div className="page-wrap">
    <div className="detail-topline"><Link to={backTo} className="back-link"><ArrowLeft size={17} />{backLabel}</Link><span>/</span><span>{displayName || platformCreatorId}</span></div>
    <div className="creator-detail-head"><div><div className="creator-avatar">{displayName ? <UserRound size={24} /> : <UserRound size={24} />}</div><div><h1>{displayName || "未提供昵称"}</h1><p>{platformLabel[platform]} · 直播广场 · {platformCreatorId}</p></div></div><div className="creator-detail-actions">{liveHref && <Link className="button ghost" to={liveHref}>直播资料</Link>}{videoHref && <Link className="button ghost" to={videoHref}>短视频资料</Link>}{actions}</div></div>
    <section className="panel library-detail-panel">
      <div className="panel-heading"><div><h2>直播表现</h2><p>{scopeLabel}{observedAt ? ` · 观测于 ${formatDate(observedAt)}` : ""}</p></div><span>平台原生口径</span></div>
      <div className="metric-strip">{metrics.map((metric) => <div className="metric" key={metric.key}><span>{metric.label}</span><strong>{metric.value}</strong><small>{metric.status === "COLLECTED" ? (metric.period || "已采集") : metric.status}</small></div>)}</div>
    </section>
    <section className="panel library-detail-panel">
      <div className="panel-heading"><div><h2>数据说明</h2><p>直播与短视频指标不混用；空值/无权限不显示为 0。</p></div></div>
      <ul className="condition-summary">
        <li>平台：{platformLabel[platform]}</li>
        <li>场景：直播广场</li>
        <li>达人 ID：{platformCreatorId}</li>
        <li>内部 ID：{creatorId}</li>
        {availableScenes && <li>可用资料：{availableScenes.map((scene) => scene === "live_square" ? "直播" : "短视频").join(" / ")}</li>}
        <li>字段来源与统计周期以每项指标下方说明为准。</li>
      </ul>
      <div className="profile-exclusion"><RefreshCcw size={15} />手动更新直播资料只刷新直播数据，不覆盖短视频数据。</div>
      <div className="submit-assurance"><ExternalLink size={16} /><span>详情数据来自本系统直播快照；平台页面可能随时变化。</span></div>
    </section>
  </div>;
}
