/**
 * Read-only presentation helpers for the Xingtu live creator detail page.
 *
 * The backend stores the live-detail modules as `StructuredValue.data` inside the immutable
 * snapshot.  These functions only unpack that envelope; they never derive a business value that the
 * platform did not return.  A missing metric keeps its platform reason instead of becoming 0.
 */
import { countText, ratioPercentText } from "./format";

export type JsonRecord = Record<string, unknown>;

export interface FieldEnvelope {
  field_key?: string;
  value?: unknown;
  raw_value?: string | null;
  status?: string;
  unit?: string | null;
  period_label?: string | null;
  observed_at?: string | null;
  path_ref?: string | null;
  failure_reason?: string | null;
}

export interface StoredModule {
  fields?: FieldEnvelope[];
  status?: string;
}

export interface MetricEnvelope {
  raw?: string | null;
  value?: string | number | null;
  unit?: string | null;
  status?: string;
  reason?: string | null;
  bound?: string | null;
  range?: { min?: string; max?: string; unit?: string } | null;
  note?: string | null;
  unit_confidence?: string | null;
}

export interface CalibreData {
  period?: number | null;
  period_label?: string | null;
  flow_type?: number | null;
  excluded_marketing?: boolean | null;
  only_star_order?: boolean;
  groups?: Record<string, Record<string, MetricEnvelope> | string | undefined>;
  interpretation?: Record<string, MetricEnvelope>;
  source?: JsonRecord;
}

export interface OverviewData {
  live_type?: string;
  live_type_label?: string;
  request_live_type?: number;
  calibres?: Record<string, CalibreData>;
  captured_periods?: number[];
}

export interface RoomRow {
  room_id?: string | null;
  title?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  duration_seconds?: number | null;
  live_type?: string | null;
  live_type_label?: string | null;
  live_type_status?: string;
  live_type_reason?: string;
  metrics?: Record<string, MetricEnvelope>;
  flags?: Record<string, unknown>;
  brands?: string[];
}

export interface CalendarData {
  live_type?: string;
  live_type_label?: string;
  months?: Array<{
    year?: number | null;
    month?: number | null;
    month_label?: string | null;
    days?: Array<{ date: string; rooms: RoomRow[] }>;
    room_count?: number;
    highest_room?: RoomRow | null;
    latest_room?: RoomRow | null;
  }>;
}

export interface LatestData {
  live_type?: string;
  window?: number;
  points?: Array<{ index: number; room_id?: string | null; start_time?: string | null; metrics?: Record<string, MetricEnvelope> }>;
  series?: Record<string, Array<{ index: number; date?: string | null; raw?: string | null; value?: string | number | null; status?: string }>>;
  highest_room?: RoomRow | null;
}

export interface AudienceData {
  live_type?: string;
  live_type_label?: string;
  crowd_type?: string;
  crowd_type_label?: string;
  distributions?: Record<
    string,
    {
      type_display?: string;
      description?: string | null;
      items?: Array<{ key?: string | null; raw?: string | null; count?: string | null; ratio?: string | null; percent?: number | null }>;
      total?: string | null;
      top10?: Array<{ key?: string | null; raw?: string | null; count?: string | null; ratio?: string | null; percent?: number | null }>;
    }
  >;
}

export interface PricingData {
  services?: Array<{
    service_label?: string;
    pricing_mode?: string;
    unit?: string | null;
    currency?: string;
    price?: MetricEnvelope;
    origin_price?: MetricEnvelope;
    platform?: JsonRecord;
  }>;
}

export function record(value: unknown): JsonRecord | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : null;
}

export function moduleOf(payload: unknown, key: string): StoredModule | null {
  const modules = record(record(payload)?.modules);
  return record(modules?.[key]) as StoredModule | null;
}

export function fieldsOf(payload: unknown, key: string): Record<string, FieldEnvelope> {
  const module = moduleOf(payload, key);
  const result: Record<string, FieldEnvelope> = {};
  for (const field of module?.fields ?? []) {
    if (field?.field_key) result[field.field_key] = field;
  }
  return result;
}

export function structuredOf(field: FieldEnvelope | undefined): JsonRecord | null {
  const value = record(field?.value);
  if (!value || value.kind !== "structured") return null;
  return record(value.data);
}

export function fieldData<T>(payload: unknown, moduleKey: string, fieldKey: string): T | null {
  return structuredOf(fieldsOf(payload, moduleKey)[fieldKey]) as T | null;
}

export function metricsOf(calibre: CalibreData | null, group: string): Record<string, MetricEnvelope> {
  const value = record(calibre?.groups?.[group]);
  return value as Record<string, MetricEnvelope>;
}

const METRIC_LABELS: Record<string, string> = {
  room_cnt: "近期直播场次",
  watch_ucnt_avg: "平均观看人数",
  watch_cnt_avg: "平均观看人次",
  acu: "ACU",
  pcu: "PCU",
  fans_watch_rate: "粉丝观看占比",
  follow_ucnt_avg: "场均涨粉数",
  comment_rate_avg: "场均评论率",
  like_rate_avg: "场均点赞率",
  watch_duration_avg: "平均看播时长",
  interact_rate_avg: "场均互动率",
  acu_precede_percent: "同粉段 ACU 排名",
  finish_order_cnt: "完成订单数",
  in_process_order_cnt: "进行中订单数",
  ecom_live_product_num: "带货商品数",
  avg_gmv_range: "场均 GMV",
  avg_ecom_product_price_range: "带货商品客单价",
  avg_gpm_range: "GPM",
  ctr_avg: "场均 CTR",
  handle_ctr_avg: "小手柄场均 CTR",
  snowflake_ctr_avg: "小雪花场均 CTR",
  windmill_ctr_avg: "小风车场均 CTR",
  handle_cvr_avg: "小手柄场均 CVR",
  watch_ucnt: "观看人数",
  watch_cnt: "观看人次",
  comment_rate: "评论率",
  like_rate: "点赞率",
  ctr: "CTR",
  gmv_range: "GMV",
  follow_ucnt: "涨粉数",
  acu_rank_rate: "ACU 排名",
};

export function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key;
}

function secondsText(value: number | string): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return String(value);
  const seconds = Math.max(0, Math.round(amount));
  return `${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, "0")}秒`;
}

/** One platform metric in its own unit; never cross-scales counts, ratios or money. */
export function metricText(metric: MetricEnvelope | undefined): string {
  if (!metric) return "暂无数据";
  if (metric.status !== "COLLECTED") {
    if (metric.reason) return metric.reason;
    if (metric.status === "FAILED") return "采集失败";
    if (metric.status === "NO_PERMISSION") return "无权限";
    if (metric.status === "UNPARSED") return metric.raw ?? "无法解析";
    return "平台未提供";
  }
  if (metric.range) {
    // A single platform value arrives as a degenerate range (0~0); show its raw value, not a
    // fabricated interval.
    if (metric.range.min !== undefined && metric.range.min === metric.range.max) {
      return metric.raw ?? String(metric.range.min);
    }
    return `${metric.range.min ?? "?"} ~ ${metric.range.max ?? "?"}`;
  }
  if (metric.value === null || metric.value === undefined) {
    return metric.raw ?? "暂无数据";
  }
  if (metric.unit === "ratio") return ratioPercentText(metric.value);
  if (metric.unit === "second") return secondsText(metric.value);
  if (metric.unit === "count") return countText(metric.value);
  return String(metric.value);
}

export function metricNote(metric: MetricEnvelope | undefined): string | null {
  if (!metric) return null;
  const parts: string[] = [];
  if (metric.status && metric.status !== "COLLECTED") parts.push(`状态 ${metric.status}`);
  if (metric.bound === "approximate") parts.push("平台近似值");
  if (metric.bound === "lower") parts.push("平台下界值");
  if (metric.unit_confidence === "ambiguous") parts.push("单位待确认");
  if (metric.note) parts.push(metric.note);
  if (metric.raw && metric.raw !== metric.value) parts.push(`原值 ${metric.raw}`);
  return parts.length ? parts.join(" · ") : null;
}

export function calibreEntries(overview: OverviewData | null): Array<{ key: string; data: CalibreData }> {
  const entries = Object.entries(overview?.calibres ?? {});
  return entries
    .map(([key, data]) => ({ key, data: data as CalibreData }))
    .sort((left, right) => {
      const period = (left.data.period ?? 0) - (right.data.period ?? 0);
      if (period !== 0) return period;
      const flow = (left.data.flow_type ?? 0) - (right.data.flow_type ?? 0);
      if (flow !== 0) return flow;
      return Number(Boolean(left.data.only_star_order)) - Number(Boolean(right.data.only_star_order));
    });
}

export function pickCalibre(
  overview: OverviewData | null,
  period: number | null,
  excludedMarketing: boolean | null,
  onlyStarOrder: boolean,
): CalibreData | null {
  const entries = calibreEntries(overview);
  if (!entries.length) return null;
  const exact = entries.find(
    (item) =>
      (period === null || item.data.period === period) &&
      (excludedMarketing === null || item.data.excluded_marketing === excludedMarketing) &&
      Boolean(item.data.only_star_order) === onlyStarOrder,
  );
  if (exact) return exact.data;
  const samePeriod = entries.find((item) => period === null || item.data.period === period);
  return (samePeriod ?? entries[0]).data;
}

export function overviewTypes(payload: unknown): Array<{ key: string; label: string }> {
  const order = ["general", "game", "ecom", "other"];
  const labels: Record<string, string> = {
    general: "不限",
    game: "游戏直播",
    ecom: "电商带货",
    other: "其它直播",
  };
  return order
    .filter((key) => Boolean(fieldData<OverviewData>(payload, "live_overview", `overview.${key}`)))
    .map((key) => ({ key, label: labels[key] ?? key }));
}

export function audienceTypes(payload: unknown): Array<{ key: string; label: string }> {
  const labels: Record<string, string> = {
    general: "不限",
    game: "游戏直播",
    ecom: "电商带货",
    other: "其它直播",
  };
  return ["general", "game", "ecom", "other"]
    .filter((key) => ["fans", "user"].some((crowd) => Boolean(fieldData(payload, "live_audience", `audience.${key}.${crowd}`))))
    .map((key) => ({ key, label: labels[key] ?? key }));
}

export function crowdTypes(payload: unknown, liveType: string): Array<{ key: string; label: string }> {
  const labels: Record<string, string> = { fans: "粉丝画像", user: "观众画像" };
  return ["fans", "user"]
    .filter((crowd) => Boolean(fieldData(payload, "live_audience", `audience.${liveType}.${crowd}`)))
    .map((key) => ({ key, label: labels[key] ?? key }));
}

export function pricingServices(payload: unknown): NonNullable<PricingData["services"]> {
  return fieldData<PricingData>(payload, "live_pricing", "pricing.services")?.services ?? [];
}

export function calendarData(payload: unknown, liveType: string): CalendarData | null {
  return fieldData<CalendarData>(payload, "live_analysis", `analysis.${liveType}.calendar`);
}

export function latestData(payload: unknown, liveType: string): LatestData | null {
  return fieldData<LatestData>(payload, "live_analysis", `analysis.${liveType}.latest`);
}

export function roomsData(payload: unknown): { rows?: RoomRow[]; item_count?: number; pagination?: JsonRecord } | null {
  return fieldData(payload, "live_analysis", "analysis.rooms");
}

export function audienceData(payload: unknown, liveType: string, crowd: string): AudienceData | null {
  return fieldData<AudienceData>(payload, "live_audience", `audience.${liveType}.${crowd}`);
}

export interface DistributionItem {
  label: string;
  value: number;
  display: string;
  share: number | null;
}

export function distributionItems(data: AudienceData | null, key: string): DistributionItem[] {
  const distribution = data?.distributions?.[key];
  if (!distribution?.items?.length) return [];
  const total = distribution.items.reduce((sum, item) => sum + Number(item.count ?? 0), 0);
  return distribution.items.map((item) => {
    const value = Number(item.count ?? 0);
    return {
      label: String(item.key ?? "未命名"),
      value,
      display: `${value.toLocaleString("zh-CN")} · ${(Number(item.percent ?? 0)).toFixed(1)}%`,
      share: total > 0 ? (value / total) * 100 : null,
    };
  });
}

export function distributionTop10(data: AudienceData | null, key: string): DistributionItem[] {
  const distribution = data?.distributions?.[key];
  if (!distribution?.top10?.length) return [];
  const total = data?.distributions?.[key]?.total ? Number(data.distributions[key]?.total) : 0;
  return distribution.top10.map((item) => {
    const value = Number(item.count ?? 0);
    return {
      label: String(item.key ?? "未命名"),
      value,
      display: `${value.toLocaleString("zh-CN")} · ${(Number(item.percent ?? 0)).toFixed(1)}%`,
      share: total > 0 ? (value / total) * 100 : null,
    };
  });
}

export function roomMetric(row: RoomRow, key: string): MetricEnvelope | undefined {
  return row.metrics?.[key];
}

export function roomTypeText(row: RoomRow): string {
  if (row.live_type_label) return row.live_type_label;
  if (row.live_type_status === "NOT_PROVIDED") return row.live_type_reason ?? "平台未提供直播类型";
  return "平台未提供直播类型";
}

export function roomTitle(row: RoomRow): string {
  return row.title?.trim() || `直播间 ${row.room_id ?? ""}`.trim();
}

export function roomDurationText(row: RoomRow): string {
  if (row.duration_seconds === null || row.duration_seconds === undefined) return "—";
  return secondsText(row.duration_seconds);
}

export function moduleFallback(payload: unknown, moduleKey: string): string | null {
  const fallbacks = record(record(payload)?.module_fallbacks);
  const entry = record(fallbacks?.[moduleKey]);
  if (!entry) return null;
  const observed = typeof entry.observed_at === "string" ? entry.observed_at : null;
  return observed ? `本次更新未采集，展示 ${observed.slice(0, 10)} 的历史数据` : "本次更新未采集，展示历史数据";
}

export function introductionText(payload: unknown): string | null {
  const value = fieldsOf(payload, "basic").introduction?.value;
  return typeof value === "string" && value.trim() ? value : null;
}

export function basicText(payload: unknown, key: string): string | null {
  const value = fieldsOf(payload, "basic")[key]?.value;
  return typeof value === "string" && value.trim() ? value : null;
}

export function basicList(payload: unknown, key: string): string[] {
  const value = fieldsOf(payload, "basic")[key]?.value;
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function rangeText(metric: MetricEnvelope | undefined): string {
  return metricText(metric);
}
