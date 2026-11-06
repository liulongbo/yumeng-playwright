/**
 * Presentation model for the Juxing live creator detail page.
 *
 * The snapshot payload is the source of truth for field status (including NO_DATA/FAILED and
 * whether the latest collection attempted the field).  `live_metrics` is only a fallback for a
 * field that is missing/uncollected in the latest payload; the UI labels such values as a previous
 * successful value instead of pretending they are part of the latest observation.
 */
import type { LiveMetricEnvelope } from "./types";
import { countText, countUnitText, fieldStatusText, plainDateText } from "./format";

export type LiveStatus = string;

export interface Resolved {
  key: string;
  field: LiveMetricEnvelope | null;
  value: unknown;
  status: LiveStatus;
  fallback: boolean;
}

export interface Quote {
  pageLabel: string;
  priceTypeName: string | null;
  priceYuan: number | null;
  priceRaw: number | null;
  currency: string;
  originalPriceYuan: number | null;
}

export interface DistPoint {
  label: string;
  rawLabel: string;
  value: number;
  tgi: number | null;
}

export interface WorkItem {
  streamId: string;
  collectionKind: string;
  title: string | null;
  coverUrl: string | null;
  mediaUrl: string | null;
  publishedAt: string | null;
  durationSeconds: number | null;
  viewCount: number | null;
  peakOnlineCount: number | null;
  likeCount: number | null;
  commentCount: number | null;
  shareCount: number | null;
  hasSkuInfo: boolean;
  orderId: string | null;
}

export interface FrequencyMode {
  label: string;
  items: Array<{ key: string; label: string; value: number }>;
}

export interface TrendPoint {
  label: string;
  value: number;
}

export interface IndexDimension {
  key: string;
  label: string;
  value: number;
}

export interface IndexTrendSeries {
  key: string;
  label: string;
  points: TrendPoint[];
}

export interface FansPeriod {
  days: 30 | 90;
  label: string;
  growth: Resolved;
  rate: Resolved;
  trend: Resolved;
  totalSeries: TrendPoint[];
  incrementSeries: TrendPoint[];
}

export interface CommercePeriod {
  days: 7 | 30 | 90;
  label: string;
  field: Resolved;
  liveCount: number | null;
  watchMedian: number | null;
  maxOnlineMedian: number | null;
  goodsCount: number | null;
  graph: Array<{ label: string; value: number }>;
  zeroMeansNoData: boolean;
}

export interface ReviewItem {
  reviewKey: string;
  comprehensive: number | null;
  contentQuality: number | null;
  cooperation: number | null;
  credit: number | null;
  content: string;
  contentRedacted: boolean;
  occurredAt: string | null;
  reviewerLabel: string;
  promotionType: number | null;
  haveAgent: boolean;
}

export interface PortraitSide {
  side: "viewer" | "fan";
  dimensions: Record<string, DistPoint[]>;
  availability: Record<string, string>;
}

export interface JuxingLiveModel {
  fields: Record<string, Resolved>;
  modules: string[];
  isLegacy: boolean;
  basic: {
    nickname: Resolved;
    avatar: Resolved;
    creatorId: Resolved;
    starId: Resolved;
    location: Resolved;
    city: Resolved;
    followers: Resolved;
    contentTypes: Resolved;
    contentForms: Resolved;
    industries: Resolved;
    mcn: Resolved;
    verified: Resolved;
  };
  quotes: Quote[];
  quotesField: Resolved;
  overview: {
    expectViewer: Resolved;
    maxOnline: Resolved;
    expectCpm: Resolved;
    weeklySessions: Resolved;
    creditScore: Resolved;
    expectMaxOnline: Resolved;
    cooperationIndustries: Resolved;
    viewerFeatureTags: Resolved;
    viewerDeviceTags: Resolved;
    viewerAreaTags: Resolved;
    supplements: Resolved[];
  };
  fans: Record<"30" | "90", FansPeriod>;
  index: {
    score: Resolved;
    dimensions: Resolved;
    industryRank: Resolved;
    industryPercent: Resolved;
    fansRank: Resolved;
    fansPercent: Resolved;
    trend: Resolved;
    current: IndexDimension[];
    sameFansAvg: IndexDimension[];
    missingAvgDimensions: string[];
    selectable: string[];
    trendSeries: IndexTrendSeries[];
    allZero: boolean;
  };
  works: {
    personal: Resolved;
    commercial: Resolved;
    recent: Resolved;
    frequency: Resolved;
    personalItems: WorkItem[];
    commercialItems: WorkItem[];
    recentItems: WorkItem[];
    frequencyModes: Record<string, FrequencyMode>;
  };
  audience: {
    viewer: Resolved;
    fan: Resolved;
    viewerSide: PortraitSide | null;
    fanSide: PortraitSide | null;
  };
  commerce: {
    periods: Record<"7" | "30" | "90", CommercePeriod>;
    hotBrands: Resolved;
    hotCategories: Resolved;
  };
  cooperation: {
    days30: {
      accept: Resolved;
      complete: Resolved;
      completed: Resolved;
    };
    days90: {
      accept: Resolved;
      complete: Resolved;
      completed: Resolved;
    };
    summary: Resolved;
    total: Resolved;
    reviews: Resolved;
    reviewItems: ReviewItem[];
    reviewMeta: {
      total: number | null;
      collected: number;
      pages: number;
      complete: boolean;
    };
  };
}

type PayloadRecord = Record<string, unknown>;

function record(value: unknown): PayloadRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as PayloadRecord)
    : null;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

export function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value.replace(/,/g, "").trim());
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function fieldInnerValue(field: LiveMetricEnvelope | null): unknown {
  if (!field) return null;
  const value = field.value;
  const item = record(value);
  if (!item) return value ?? null;
  if ("data" in item) return item.data;
  if ("amount" in item) {
    const amount = numberValue(item.amount);
    return amount ?? item.amount;
  }
  return value ?? null;
}

export function flattenLivePayload(payload: PayloadRecord | undefined): Record<string, LiveMetricEnvelope> {
  const out: Record<string, LiveMetricEnvelope> = {};
  const modules = payload?.modules;
  if (!modules || typeof modules !== "object") return out;
  for (const module of Object.values(modules as PayloadRecord)) {
    const fields = record(module)?.fields;
    if (!Array.isArray(fields)) continue;
    for (const raw of fields) {
      const field = record(raw);
      const key = text(field?.field_key);
      if (field && key) out[key] = field as LiveMetricEnvelope;
    }
  }
  return out;
}

function mergeFields(
  payload: PayloadRecord | undefined,
  liveMetrics?: Record<string, LiveMetricEnvelope>,
): { fields: Record<string, LiveMetricEnvelope>; fallback: Set<string> } {
  const fields = flattenLivePayload(payload);
  const fallback = new Set<string>();
  for (const [key, value] of Object.entries(liveMetrics ?? {})) {
    const current = fields[key];
    if (!current || current.status !== "COLLECTED") {
      fields[key] = value;
      fallback.add(key);
    }
  }
  return { fields, fallback };
}

export function resolveStatus(field: LiveMetricEnvelope | null): LiveStatus {
  return field?.status ?? "MISSING";
}

export function statusText(field: LiveMetricEnvelope | null): string {
  if (!field) return "尚未采集";
  if (field.status === "COLLECTED") return "已采集";
  return fieldStatusText(field.status);
}

export function isCollected(field: LiveMetricEnvelope | null): boolean {
  return field?.status === "COLLECTED";
}

export function collectableText(field: LiveMetricEnvelope | null, fallback = "暂无数据"): string {
  if (!field) return "尚未采集";
  if (field.status !== "COLLECTED") return statusText(field);
  const value = fieldInnerValue(field);
  const textValue = text(value);
  return textValue ?? fallback;
}

export function formatPercent(value: unknown, digits = 1): string {
  const number = numberValue(value);
  if (number === null) return "暂无数据";
  return `${(number * 100).toFixed(digits)}%`;
}

export function formatScore(value: unknown): string {
  const number = numberValue(value);
  return number === null ? "暂无数据" : number.toFixed(1);
}

/** Index scores are displayed at the platform's precision (81.6, 85.25) without fake zeros. */
export function formatIndexScore(value: unknown): string {
  const number = numberValue(value);
  if (number === null) return "暂无数据";
  return number.toFixed(2).replace(/\.?0+$/, "");
}

export function formatCount(value: unknown): string {
  const number = numberValue(value);
  return number === null ? "暂无数据" : countText(number);
}

export function formatUnitCount(value: unknown): string {
  const number = numberValue(value);
  return number === null ? "暂无数据" : countUnitText(number);
}

export function formatMoney(value: unknown): string {
  const number = numberValue(value);
  return number === null ? "暂无数据" : `¥${number.toLocaleString("zh-CN")}`;
}

export function formatDate(value: unknown): string {
  const textValue = text(value);
  if (!textValue) return "暂无数据";
  return plainDateText(textValue);
}

export function formatDuration(seconds: unknown): string {
  const value = numberValue(seconds);
  if (value === null) return "暂无数据";
  const minutes = Math.max(0, Math.round(value / 60));
  if (minutes < 60) return `${minutes}分钟`;
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  return remaining ? `${hours}小时${remaining}分钟` : `${hours}小时`;
}

export function formatRange(observedAt: string | null | undefined, days: number): string {
  if (!observedAt) return `近${days}天`;
  const end = new Date(observedAt);
  if (Number.isNaN(end.getTime())) return `近${days}天`;
  end.setDate(end.getDate() - 1);
  const start = new Date(end);
  start.setDate(start.getDate() - (days - 1));
  const format = (value: Date) =>
    `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(
      value.getDate(),
    ).padStart(2, "0")}`;
  return `${format(start)} ~ ${format(end)}`;
}

function asDistPoints(value: unknown): DistPoint[] {
  return list(value)
    .map((raw) => {
      const item = record(raw);
      if (!item) return null;
      const label = text(item.label);
      const number = numberValue(item.value);
      if (!label || number === null) return null;
      return {
        label,
        rawLabel: text(item.raw_label) ?? label,
        value: number,
        tgi: numberValue(item.tgi),
      };
    })
    .filter((item): item is DistPoint => item !== null);
}

function asTrendPoints(value: unknown): TrendPoint[] {
  return list(value)
    .map((raw) => {
      const item = record(raw);
      if (!item) return null;
      const rawLabel = text(item.date) ?? text(item.raw_label) ?? text(item.period);
      const label =
        rawLabel && /^\d{6}$/.test(rawLabel)
          ? `${rawLabel.slice(0, 4)}-${rawLabel.slice(4)}`
          : rawLabel;
      const number = numberValue(item.value);
      if (!label || number === null) return null;
      return { label, value: number };
    })
    .filter((item): item is TrendPoint => item !== null);
}

function asWorks(value: unknown): WorkItem[] {
  return list(value)
    .map((raw) => {
      const item = record(raw);
      if (!item) return null;
      const streamId = text(item.stream_id);
      if (!streamId) return null;
      return {
        streamId,
        collectionKind: text(item.collection_kind) ?? "personal",
        title: text(item.title),
        coverUrl: text(item.cover_url),
        mediaUrl: text(item.media_url),
        publishedAt: text(item.published_at),
        durationSeconds: numberValue(item.duration_seconds),
        viewCount: numberValue(item.view_count),
        peakOnlineCount: numberValue(item.peak_online_count),
        likeCount: numberValue(item.like_count),
        commentCount: numberValue(item.comment_count),
        shareCount: numberValue(item.share_count),
        hasSkuInfo: item.has_sku_info === true,
        orderId: text(item.order_id),
      };
    })
    .filter((item): item is WorkItem => item !== null);
}

function asPortraitSide(value: unknown, side: "viewer" | "fan"): PortraitSide | null {
  const raw = record(value);
  if (!raw) return null;
  const dimensions: Record<string, DistPoint[]> = {};
  const availability: Record<string, string> = {};
  const keys = [
    "gender",
    "age",
    "device_brand",
    "device_price",
    "device_type",
    "activity",
    "city_tier",
    "city",
    "province",
    "province_share",
    "province_penetration",
    "interest",
    "nine_major_groups",
  ];
  for (const key of keys) dimensions[key] = asDistPoints(raw[key]);
  const rawAvailability = record(raw.availability);
  for (const key of keys) {
    const status = text(rawAvailability?.[key]);
    availability[key] = status ?? (dimensions[key]?.length ? "COLLECTED" : "NO_DATA");
  }
  return { side, dimensions, availability };
}

function quoteList(value: unknown): Quote[] {
  return list(value)
    .map((raw) => {
      const item = record(raw);
      if (!item) return null;
      return {
        pageLabel: text(item.page_label) ?? text(item.price_type_name) ?? "直播报价",
        priceTypeName: text(item.price_type_name),
        priceYuan: numberValue(item.price_yuan),
        priceRaw: numberValue(item.price_raw),
        currency: text(item.currency) ?? "CNY",
        originalPriceYuan: numberValue(item.original_price_yuan),
      };
    })
    .filter((item): item is Quote => item !== null);
}

function asReviews(value: unknown): ReviewItem[] {
  return list(value)
    .map((raw) => {
      const item = record(raw);
      if (!item) return null;
      const reviewKey = text(item.review_key);
      if (!reviewKey) return null;
      return {
        reviewKey,
        comprehensive: numberValue(item.comprehensive),
        contentQuality: numberValue(item.content_quality),
        cooperation: numberValue(item.cooperation),
        credit: numberValue(item.credit),
        content: text(item.content) ?? "",
        contentRedacted: item.content_redacted === true,
        occurredAt: text(item.occurred_at),
        reviewerLabel: text(item.reviewer_label) ?? "匿名评论",
        promotionType: numberValue(item.promotion_type),
        haveAgent: item.have_agent === true,
      };
    })
    .filter((item): item is ReviewItem => item !== null);
}

export function buildJuxingLiveModel(
  payload: PayloadRecord | undefined,
  liveMetrics?: Record<string, LiveMetricEnvelope>,
): JuxingLiveModel {
  const { fields, fallback } = mergeFields(payload, liveMetrics);
  const resolve = (key: string): Resolved => {
    const field = fields[key] ?? null;
    return {
      key,
      field,
      value: fieldInnerValue(field),
      status: resolveStatus(field),
      fallback: fallback.has(key),
    };
  };
  const modules = record(payload?.modules) ? Object.keys(payload?.modules as PayloadRecord) : [];
  const isLegacy = !modules.includes("works") && !modules.includes("audience");

  const basic = {
    nickname: resolve("nickname"),
    avatar: resolve("avatar_uri"),
    creatorId: resolve("platform_creator_id"),
    starId: resolve("platform_star_id"),
    location: resolve("province"),
    city: resolve("city"),
    followers: resolve("followers"),
    contentTypes: resolve("content_type_labels"),
    contentForms: resolve("content_form_labels"),
    industries: resolve("industry_labels"),
    mcn: resolve("mcn_name"),
    verified: resolve("verified_info"),
  };

  const quoteField = resolve("live.quote_details");
  let quotes: Quote[] = quoteList(quoteField.value);
  if (!quotes.length) {
    const legacyQuotes: Array<[string, string]> = [
      ["按小时/1小时", "live.quote_hour"],
      ["按天/1天", "live.quote_day"],
      ["按商品/1个商品(拼场直播)", "live.quote_goods"],
    ];
    const fallbackQuotes: Quote[] = [];
    for (const [pageLabel, key] of legacyQuotes) {
      const amount = numberValue(resolve(key).value);
      if (amount === null) continue;
      fallbackQuotes.push({
        pageLabel,
        priceTypeName: null,
        priceYuan: amount,
        priceRaw: null,
        currency: "CNY",
        originalPriceYuan: null,
      });
    }
    quotes = fallbackQuotes;
  }

  const fans: Record<"30" | "90", FansPeriod> = {
    "30": {
      days: 30,
      label: "近30天",
      growth: resolve("live.follower_growth_30d"),
      rate: resolve("live.follower_growth_rate_30d"),
      trend: resolve("live.follower_trend_30d"),
      totalSeries: asTrendPoints(record(resolve("live.follower_trend_30d").value)?.total_series),
      incrementSeries: asTrendPoints(
        record(resolve("live.follower_trend_30d").value)?.increment_series,
      ),
    },
    "90": {
      days: 90,
      label: "近90天",
      growth: resolve("live.follower_growth_90d"),
      rate: resolve("live.follower_growth_rate_90d"),
      trend: resolve("live.follower_trend_90d"),
      totalSeries: asTrendPoints(record(resolve("live.follower_trend_90d").value)?.total_series),
      incrementSeries: asTrendPoints(
        record(resolve("live.follower_trend_90d").value)?.increment_series,
      ),
    },
  };

  const indexDimensions = record(resolve("live.index_dimensions").value);
  const current = list(indexDimensions?.current)
    .map((raw) => {
      const item = record(raw);
      const key = text(item?.key);
      const label = text(item?.label);
      const value = numberValue(item?.value);
      return key && label && value !== null ? { key, label, value } : null;
    })
    .filter((item): item is IndexDimension => item !== null);
  const sameFansAvg = list(indexDimensions?.same_fans_segment_avg)
    .map((raw) => {
      const item = record(raw);
      const key = text(item?.key);
      const label = text(item?.label);
      const value = numberValue(item?.value);
      return key && label && value !== null ? { key, label, value } : null;
    })
    .filter((item): item is IndexDimension => item !== null);
  const indexTrendRaw = record(resolve("live.index_trend").value);
  const trendSeries = list(indexTrendRaw?.series)
    .map((raw) => {
      const item = record(raw);
      const key = text(item?.key);
      const label = text(item?.label);
      if (!key || !label) return null;
      return { key, label, points: asTrendPoints(item?.points) };
    })
    .filter((item): item is IndexTrendSeries => item !== null);
  const selectable = list(indexTrendRaw?.selectable)
    .map((value) => text(value))
    .filter((value): value is string => Boolean(value));

  const worksRaw = {
    personal: resolve("live.personal_live_works"),
    commercial: resolve("live.commercial_live_works"),
    recent: resolve("live.recent_live_works"),
    frequency: resolve("live.live_frequency"),
  };
  const frequencyRaw = record(worksRaw.frequency.value);
  const frequencyModes: Record<string, FrequencyMode> = {};
  for (const [mode, raw] of Object.entries(record(frequencyRaw?.modes) ?? {})) {
    const modeRecord = record(raw);
    if (!modeRecord) continue;
    frequencyModes[mode] = {
      label: text(modeRecord.label) ?? mode,
      items: list(modeRecord.items)
        .map((item) => {
          const entry = record(item);
          const key = text(entry?.key);
          const label = text(entry?.label);
          const value = numberValue(entry?.value);
          return key && label && value !== null ? { key, label, value } : null;
        })
        .filter((item): item is { key: string; label: string; value: number } => item !== null),
    };
  }

  const viewerPortraitRaw = resolve("live.viewer_portrait");
  const fanPortraitRaw = resolve("live.fan_portrait");
  const viewerSide = asPortraitSide(viewerPortraitRaw.value, "viewer");
  const fanSide = asPortraitSide(fanPortraitRaw.value, "fan");

  const commerceField = (days: 7 | 30 | 90) => resolve(`live.commerce_${days}d`);
  const commercePeriods: Record<"7" | "30" | "90", CommercePeriod> = {} as Record<
    "7" | "30" | "90",
    CommercePeriod
  >;
  for (const days of [7, 30, 90] as const) {
    const field = commerceField(days);
    let raw = record(field.value);
    if (!raw && days === 7) {
      // Old snapshots only have the four legacy seven-day commerce fields.  Show those as a
      // legacy seven-day attempt rather than pretending the new structured field was collected.
      const legacyLive = resolve("live.commerce_sessions");
      if (legacyLive.field) {
        raw = {
          live_cnt: numberValue(legacyLive.value),
          live_watch_cnt_median: numberValue(resolve("live.commerce_watch_median").value),
          live_max_online_cnt_median: numberValue(
            resolve("live.commerce_max_online_median").value,
          ),
          goods_cnt: numberValue(resolve("live.commerce_goods").value),
          goods_graph: [],
          zero_means_no_data: legacyLive.status === "NO_DATA",
        };
      }
    }
    commercePeriods[String(days) as "7" | "30" | "90"] = {
      days,
      label: `近${days}日`,
      field,
      liveCount: numberValue(raw?.live_cnt),
      watchMedian: numberValue(raw?.live_watch_cnt_median),
      maxOnlineMedian: numberValue(raw?.live_max_online_cnt_median),
      goodsCount: numberValue(raw?.goods_cnt),
      graph: list(raw?.goods_graph)
        .map((item) => {
          const entry = record(item);
          const label = text(entry?.range);
          const value = numberValue(entry?.count);
          return label && value !== null ? { label, value } : null;
        })
        .filter((item): item is { label: string; value: number } => item !== null),
      zeroMeansNoData: raw?.zero_means_no_data === true,
    };
  }

  const reviewsRaw = record(resolve("live.evaluation_reviews").value);
  const summaryRaw = record(resolve("live.evaluation_summary").value);
  const reviewItems = asReviews(reviewsRaw?.items);
  const reviewTotal = numberValue(reviewsRaw?.total);
  const resolvedFields: Record<string, Resolved> = Object.fromEntries(
    Object.keys(fields).map((key) => [key, resolve(key)]),
  );

  return {
    fields: resolvedFields,
    modules,
    isLegacy,
    basic,
    quotes,
    quotesField: quoteField,
    overview: {
      expectViewer: resolve("live.expect_viewer"),
      maxOnline: resolve("live.max_online"),
      expectCpm: resolve("live.expect_cpm"),
      weeklySessions: resolve("live.weekly_sessions"),
      creditScore: resolve("live.credit_score"),
      expectMaxOnline: resolve("live.expect_max_online"),
      cooperationIndustries: resolve("live.cooperation_industries"),
      viewerFeatureTags: resolve("live.viewer_feature_tags"),
      viewerDeviceTags: resolve("live.viewer_device_tags"),
      viewerAreaTags: resolve("live.viewer_area_tags"),
      supplements: [
        resolve("live.avg_people"),
        resolve("live.avg_like"),
        resolve("live.week_release"),
        resolve("live.interaction_rate"),
      ],
    },
    fans,
    index: {
      score: resolve("live.index_score"),
      dimensions: resolve("live.index_dimensions"),
      industryRank: resolve("live.index_industry_rank"),
      industryPercent: resolve("live.index_industry_percent"),
      fansRank: resolve("live.index_fans_rank"),
      fansPercent: resolve("live.index_fans_percent"),
      trend: resolve("live.index_trend"),
      current,
      sameFansAvg,
      missingAvgDimensions: list(indexDimensions?.missing_avg_dimensions)
        .map((value) => text(value))
        .filter((value): value is string => Boolean(value)),
      selectable,
      trendSeries,
      allZero: indexTrendRaw?.all_zero === true,
    },
    works: {
      ...worksRaw,
      personalItems: asWorks(worksRaw.personal.value),
      commercialItems: asWorks(worksRaw.commercial.value),
      recentItems: asWorks(worksRaw.recent.value),
      frequencyModes,
    },
    audience: {
      viewer: viewerPortraitRaw,
      fan: fanPortraitRaw,
      viewerSide,
      fanSide,
    },
    commerce: {
      periods: commercePeriods,
      hotBrands: resolve("live.hot_brands"),
      hotCategories: resolve("live.hot_categories"),
    },
    cooperation: {
      days30: {
        accept: resolve("live.accept_order_rate_30d"),
        complete: resolve("live.complete_order_rate_30d"),
        completed: resolve("live.completed_orders_30d"),
      },
      days90: {
        accept: resolve("live.accept_order_rate_90d"),
        complete: resolve("live.complete_order_rate_90d"),
        completed: resolve("live.completed_orders_90d"),
      },
      summary: resolve("live.evaluation_summary"),
      total: resolve("live.evaluation_total"),
      reviews: resolve("live.evaluation_reviews"),
      reviewItems,
      reviewMeta: {
        total: reviewTotal ?? numberValue(resolve("live.evaluation_total").value),
        collected: numberValue(reviewsRaw?.collected) ?? reviewItems.length,
        pages: numberValue(reviewsRaw?.pages) ?? 0,
        complete: reviewsRaw?.complete === true,
      },
    },
  };
}

export function textList(value: unknown): string[] {
  return list(value)
    .map((item) => text(item))
    .filter((item): item is string => Boolean(item));
}

export function structuredArray(value: unknown): PayloadRecord[] {
  return list(value)
    .map((item) => record(item))
    .filter((item): item is PayloadRecord => item !== null);
}

export function asRecord(value: unknown): PayloadRecord | null {
  return record(value);
}

export function hotBrandList(value: unknown): Array<{ title: string; rank: number | null }> {
  return structuredArray(value)
    .map((item) => {
      const title = text(item.title);
      return title ? { title, rank: numberValue(item.rank) } : null;
    })
    .filter((item): item is { title: string; rank: number | null } => item !== null);
}

export function hotCategoryList(
  value: unknown,
): Array<{ title: string; rate: number | null; rank: number | null }> {
  return structuredArray(value)
    .map((item) => {
      const title = text(item.title);
      return title
        ? { title, rate: numberValue(item.rate), rank: numberValue(item.rank) }
        : null;
    })
    .filter(
      (item): item is { title: string; rate: number | null; rank: number | null } =>
        item !== null,
    );
}
