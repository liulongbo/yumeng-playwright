/**
 * 「商业能力」章节（CD-04）：传播价值 / 种草价值 / 转化价值 / 历史合作行业。
 *
 * Every value on this page comes from a platform `FieldObservation` envelope in the profile payload:
 * the module reads the same `module.field` keys the collection contract registers, formats only at
 * the display layer, and renders an explicit state (`平台暂无数据`, `—`, the platform's own `<`/`>`
 * bound) instead of inventing a number.  Nothing here writes back, and no field is recomputed from
 * another field.
 *
 * Confirmed display rules (user decision, 2026-10-15):
 * - counts: `n >= 10,000` → `93.0w`, `1,000 <= n < 10,000` → `3.0k`, below → the plain number,
 *   always rounded to one decimal (`countWanText`);
 * - the platform `overtake` integer is a 万分比 and means 「优于同类型达人 X%」 — *not* a "低于"
 *   share — one decimal (`overtakePercentText`);
 * - 种草价值 / 转化价值 return **ranges** (`"5,000 - 15,000"`, `"500以下"`, `"3万-3万"`); they are
 *   printed verbatim.  No midpoint, no average, no unit conversion, and equal bounds stay two
 *   bounds because the platform sent two bounds.
 */
import { useEffect, useState, type ReactNode } from "react";
import { ImageOff } from "lucide-react";
import { countWanText, isBlank, numberOrNull, overtakePercentText, tenThousandthsPercentText } from "../format";
import { fieldStatusText } from "../format";
import type { CatalogIndex } from "../fieldCatalog";
import { Panel, EmptyNote } from "./ui";
import { fieldView, type FieldView } from "./views";

export interface FeaturedCardView {
  card_id: string | null;
  position: number;
  platform_content_id: string | null;
  local_key: string | null;
  canonical_link: string | null;
  link_from_fields: string | null;
  cover_object_id: string | null;
  cover_status: string;
  title: string | null;
  subtitle: string | null;
  truncated_fields: string[];
  play: unknown;
  like: unknown;
  comment: unknown;
}

export interface FeaturedCollectionView {
  collection_type: "excellent_reach" | "excellent_seeding";
  status: string;
  view_kind: string;
  observed_at: string | null;
  coverage_gaps: string[];
  cards: FeaturedCardView[];
}

/** The two 精选集合 a creator detail page can show, plus its per-entry cover URL builder. */
export interface FeaturedContent {
  reach: FeaturedCollectionView | null;
  seeding: FeaturedCollectionView | null;
  coverUrl: (objectId: string) => string;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function member(view: FieldView, ...path: string[]): unknown {
  let cursor: unknown = view.data;
  for (const key of path) {
    cursor = record(cursor)?.[key];
  }
  return cursor;
}

/**
 * The state line for a field that has no value to show.
 *
 * `FieldView.state` is `null` both for a collected field with a value and for a collected field that
 * came back blank; the latter still needs its explicit state (`平台返回空值`, `平台仅返回标签[…]`),
 * so a blank value falls back to the state and only a real value leaves it empty.
 */
function pendingState(view: FieldView): string | null {
  if (!view.collected) return view.statusText;
  return view.blank ? (view.state ?? "平台暂无数据") : null;
}

function rangeOrDash(value: unknown): string {
  if (typeof value !== "string" || isBlank(value)) return "—";
  return value;
}

/**
 * A count in the confirmed 万/k form.
 *
 * Accepts both shapes the two entries deliver: a plain value (module fields) and a `FieldObservation`
 * numeric envelope `{kind, amount, bound}` (featured-card fields), so a card's 播放/点赞/评论 is
 * never rendered as a dash just because the number arrived wrapped.
 */
function countValue(value: unknown): string {
  const leaf = value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>).amount ?? value
    : value;
  const amount = numberOrNull(leaf);
  return amount === null ? "—" : countWanText(amount);
}

function compareNote(overtake: unknown): string | null {
  const text = overtakePercentText(overtake);
  return text === "—" ? null : `优于 ${text} 同类型达人`;
}

/**
 * One metric of a business module: label, value, and the platform's peer comparison when it exists.
 *
 * `platformNote` keeps the stored original reachable (the platform's own scale is not always the
 * same as what it prints), so a reviewer can always trace the shown text back to the envelope.
 */
function BizMetric({
  label,
  value,
  compare,
  platformNote,
  state,
  title,
}: {
  label: string;
  value: ReactNode;
  compare?: string | null;
  platformNote?: string | null;
  state?: string | null;
  title?: string;
}) {
  const pending = value === "—" || value === null || value === undefined;
  return (
    <div className={`biz-metric${pending ? " pending" : ""}`}>
      <span className="biz-metric-label">{label}</span>
      <strong title={title}>{value}</strong>
      {compare ? <em className="biz-compare">{compare}</em> : null}
      {!compare && state ? <em className="biz-state">{state}</em> : null}
      {platformNote ? <small className="biz-original">{platformNote}</small> : null}
    </div>
  );
}

/** 传播价值 · 内容数据 — 7 metrics in the confirmed order. */
function ContentDataPanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const spread = (key: string) => fieldView(payload, index, "spread", key);
  /**
   * 「播放量中位数」 comes from `spread.item_rate_metrics.play_mid`, **not** from the registered
   * `spread.play_median` field.
   *
   * The same response carries two different median leaves. Live-verified 2026-10-16 against
   * 巨量星图 for creator 6639192346380468227: the platform's 内容数据 card shows 76.6w / 优于
   * 99.23% 同类型达人, which is `item_rate_metrics.play_mid` = 766187 / 9923; the top-level
   * `play_mid` holds 1399516 and the platform renders it nowhere. (The separate 「播放中位数
   * 133.1w」 card beside 相关视频数 is `conversion.related_video_play_median`, a different metric.)
   * Reading `play_median` here was CD-08's defect: it printed 140.0w for a 76.6w metric. The
   * leaf chosen here is also the one `douyin_xingtu_creator_current.play_median_value_raw` is
   * backfilled from, so the stored value and the displayed value stay the same number.
   */
  const itemRate = spread("item_rate_metrics");
  const playMid = member(itemRate, "play_mid");
  const playMidValue = member(itemRate, "play_mid", "value");
  const playMidOvertake = member(itemRate, "play_mid", "overtake");
  const playMidLabel = record(playMid)?.label;
  const playMedianState = isBlank(playMidValue)
    ? itemRate.collected
      ? typeof playMidLabel === "string" && playMidLabel
        ? `平台仅返回标签「${playMidLabel}」`
        : itemRate.blank
          ? (itemRate.state ?? "平台暂无数据")
          : "平台未返回中位播放量"
      : itemRate.statusText
    : null;
  const completion = spread("completion_rate");
  const interaction = spread("interaction_rate");
  const duration = spread("average_duration");
  const likes = spread("average_likes");
  const comments = spread("average_comments");
  const shares = spread("average_shares");

  const rateValue = (view: FieldView) => {
    const raw = member(view, "value");
    if (isBlank(raw)) return "—";
    // Registered as a percent-like integer: the platform prints `value ÷ 100` (CD-02, live-checked).
    return tenThousandthsPercentText(raw);
  };
  /**
   * The state line for a rate whose `value` member is absent.
   *
   * The platform returns four observed shapes for these two fields — `{value, overtake}`,
   * `{label, value, overtake}`, `{label}` only, and `{}` — so a present envelope without a `value`
   * member must name the platform's own reason (its industry label, or an empty answer) instead of
   * rendering a bare dash.
   */
  const rateState = (view: FieldView, raw: unknown) => {
    if (!isBlank(raw)) return null;
    if (!view.collected) return view.statusText;
    if (view.blank) return view.state ?? "平台暂无数据";
    const label = record(view.data)?.label;
    return typeof label === "string" && label ? `平台仅返回标签「${label}」` : "平台暂无数据";
  };

  const durationRaw = numberOrNull(duration.data);
  const durationSeconds = durationRaw === null ? null : durationRaw / 100;

  return (
    <Panel
      title="内容数据"
      hint="数据范围：近30天。数值为平台原始观测值；同类型达人对比为该平台返回的百分位原值。"
      meta={itemRate.collected ? undefined : fieldStatusText(itemRate.status)}
    >
      <div className="biz-grid biz-grid-3">
        <BizMetric
          label="播放量中位数"
          value={isBlank(playMidValue) ? "—" : countValue(playMidValue)}
          compare={compareNote(playMidOvertake)}
          state={playMedianState}
          title={isBlank(playMidValue) ? undefined : String(playMidValue)}
          platformNote={
            isBlank(playMidValue)
              ? null
              : `平台原值 ${String(playMidValue)}${isBlank(playMidOvertake) ? "" : ` / 超越原值 ${String(playMidOvertake)}`}`
          }
        />
        <BizMetric
          label="完播率"
          value={completion.collected && !isBlank(member(completion, "value")) ? rateValue(completion) : "—"}
          compare={compareNote(member(completion, "overtake"))}
          state={rateState(completion, member(completion, "value"))}
          platformNote={
            !isBlank(member(completion, "value"))
              ? `平台原值 ${String(member(completion, "value"))}${isBlank(member(completion, "overtake")) ? "" : ` / 超越原值 ${String(member(completion, "overtake"))}`}`
              : null
          }
        />
        <BizMetric
          label="互动率"
          value={interaction.collected && !isBlank(member(interaction, "value")) ? rateValue(interaction) : "—"}
          compare={compareNote(member(interaction, "overtake"))}
          state={rateState(interaction, member(interaction, "value"))}
          platformNote={
            !isBlank(member(interaction, "value"))
              ? `平台原值 ${String(member(interaction, "value"))}${isBlank(member(interaction, "overtake")) ? "" : ` / 超越原值 ${String(member(interaction, "overtake"))}`}`
              : null
          }
        />
        <BizMetric
          label="平均时长"
          value={durationSeconds === null ? "—" : `${durationSeconds.toFixed(1)} 秒`}
          state={rateState(duration, duration.data)}
          platformNote={durationRaw === null ? null : `平台原值 ${durationRaw}（秒×100）`}
        />
        <BizMetric
          label="平均点赞"
          value={likes.collected && !likes.blank ? countValue(likes.data) : "—"}
          state={rateState(likes, likes.data)}
          platformNote={!isBlank(likes.data) ? `平台原值 ${String(likes.data)}` : null}
        />
        <BizMetric
          label="平均评论"
          value={comments.collected && !comments.blank ? countValue(comments.data) : "—"}
          state={rateState(comments, comments.data)}
          platformNote={!isBlank(comments.data) ? `平台原值 ${String(comments.data)}` : null}
        />
        <BizMetric
          label="平均转发"
          value={shares.collected && !shares.blank ? countValue(shares.data) : "—"}
          state={rateState(shares, shares.data)}
          platformNote={!isBlank(shares.data) ? `平台原值 ${String(shares.data)}` : null}
        />
      </div>
    </Panel>
  );
}

/** 传播价值 · 性价比/效果预估 — the two duration bands stay separate. */
function EffortEstimatePanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const cpm = fieldView(payload, index, "spread", "expected_cpm");
  const cpe = fieldView(payload, index, "spread", "expected_cpe");
  const commercialPlay = fieldView(payload, index, "spread", "commercial_play_count");
  const naturalPlay = fieldView(payload, index, "spread", "commercial_natural_play_count");

  return (
    <Panel
      title="性价比/效果预估"
      hint="平台原始数值；21–60 秒与 60 秒以上两档分别展示，不合并、不推断币种与缩放。"
    >
      <div className="biz-grid biz-grid-4">
        <BizMetric
          label="预期 CPM（21–60 秒）"
          value={countOrDashMember(cpm, "cpm_21_60")}
          state={pendingState(cpm)}
          platformNote="平台原值 · 币种未登记"
        />
        <BizMetric
          label="预期 CPM（60 秒以上）"
          value={countOrDashMember(cpm, "cpm_60")}
          state={pendingState(cpm)}
          platformNote="平台原值 · 币种未登记"
        />
        <BizMetric
          label="预期 CPE（21–60 秒）"
          value={countOrDashMember(cpe, "cpe_21_60")}
          state={pendingState(cpe)}
          platformNote="平台原值 · 币种未登记"
        />
        <BizMetric
          label="预期 CPE（60 秒以上）"
          value={countOrDashMember(cpe, "cpe_60")}
          state={pendingState(cpe)}
          platformNote="平台原值 · 币种未登记"
        />
        <BizMetric
          label="商业播放量"
          value={commercialPlay.collected && !commercialPlay.blank ? countValue(commercialPlay.data) : "—"}
          state={pendingState(commercialPlay)}
          platformNote={
            !isBlank(commercialPlay.data) ? `平台原值 ${String(commercialPlay.data)} · 契约路径 vv` : null
          }
        />
        <BizMetric
          label="商业自然播放量"
          value={naturalPlay.collected && !naturalPlay.blank ? countValue(naturalPlay.data) : "—"}
          state={pendingState(naturalPlay)}
          platformNote={
            !isBlank(naturalPlay.data) ? `平台原值 ${String(naturalPlay.data)} · 契约路径 sn_vv` : null
          }
        />
      </div>
    </Panel>
  );
}

function countOrDashMember(view: FieldView, field: string): string {
  const value = member(view, field);
  if (isBlank(value)) return "—";
  const amount = numberOrNull(value);
  return amount === null ? String(value) : amount.toLocaleString("zh-CN");
}

/** 种草价值 — 6 metrics; the platform returns ranges and they are printed as sent. */
function SeedingValuePanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const seeding = (key: string) => fieldView(payload, index, "seeding", key);
  const metrics: Array<{ label: string; view: FieldView; note?: string }> = [
    {
      label: "商单视频平均看后搜次数",
      view: seeding("search_after_view"),
      note: "平台按区间返回；原字段名为「看后搜人数」，区间原值保留、未拆分为单条视频均值",
    },
    {
      label: "商单视频看后搜率",
      view: seeding("search_after_view_rate"),
      note: "平台按区间返回",
    },
    {
      label: "商单视频小蓝词点击率",
      view: seeding("search_word_ctr"),
      note: "原字段名「搜索词点击率」；平台按区间返回",
    },
    {
      label: "个人视频平均看后搜次数",
      view: seeding("personal_search_after_view"),
      note: "原字段名为「个人页看后搜人数」；平台按区间返回，未拆分为单条视频均值",
    },
    {
      label: "个人视频看后搜率",
      view: seeding("personal_search_after_view_rate"),
      note: "原字段名「个人页看后搜比例」；平台按区间返回",
    },
    {
      label: "A3增长数",
      view: seeding("a3_increment"),
      note: "只取 A3 增长数；库内该字段不含同行排名，故不展示排名",
    },
  ];
  return (
    <Panel
      title="种草价值"
      hint="数据范围：近90天。平台以区间返回；区间文本原样展示，不取中值、不换算为单位。"
      id="seeding"
      meta={`${metrics.filter((item) => item.view.collected && !item.view.blank).length}/${metrics.length} 有值`}
    >
      <div className="biz-grid biz-grid-3">
        {metrics.map((item) => (
          <BizMetric
            key={item.label}
            label={item.label}
            value={
              item.view.collected && !item.view.blank ? rangeOrDash(item.view.data) : "—"
            }
            state={pendingState(item.view)}
            title={typeof item.view.data === "string" ? item.view.data : undefined}
            platformNote={item.note}
          />
        ))}
      </div>
    </Panel>
  );
}

/** 转化价值 — 5 metrics; ranges (including equal bounds) are printed as the platform sent them. */
function ConversionValuePanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const conversion = (key: string) => fieldView(payload, index, "conversion", key);
  const relatedVideos = conversion("related_video_count");
  const playMedian = conversion("related_video_play_median");
  const clicks = conversion("component_click_count_range");
  const clickRate = conversion("component_click_rate_range");
  const cpc = conversion("related_cpc_range");

  return (
    <Panel
      title="转化价值"
      hint="数据范围：近30天。区间字段（组件点击量/点击率/CPC）按平台原值展示，不取中值、不推断币种。"
      id="conversion"
    >
      <div className="biz-grid biz-grid-3">
        <BizMetric
          label="相关视频数"
          value={isBlank(member(relatedVideos, "value")) ? "—" : String(member(relatedVideos, "value"))}
          state={pendingState(relatedVideos)}
          platformNote="平台原始计数值"
        />
        <BizMetric
          label="视频播放中位数"
          value={playMedian.collected && !isBlank(member(playMedian, "value")) ? countValue(member(playMedian, "value")) : "—"}
          state={pendingState(playMedian)}
          platformNote={
            isBlank(member(playMedian, "value"))
              ? null
              : `平台原值 ${String(member(playMedian, "value"))} · 原字段名「相关视频播放中位数」`
          }
        />
        <BizMetric
          label="组件点击量"
          value={rangeOrDash(clicks.data)}
          state={pendingState(clicks)}
          platformNote="平台区间值，未取平均或中点"
        />
        <BizMetric
          label="组件点击率"
          value={rangeOrDash(clickRate.data)}
          state={pendingState(clickRate)}
          platformNote="平台区间值，百分比口径与平台一致"
        />
        <BizMetric
          label="CPC"
          value={rangeOrDash(cpc.data)}
          state={pendingState(cpc)}
          platformNote="平台区间值 · 币种未登记"
        />
      </div>
    </Panel>
  );
}

/**
 * One 精选视频集合 card grid, shared by 优秀传播视频 and 优秀种草视频.
 *
 * The two collections differ only by their data source, so they share this component instead of
 * duplicating a card implementation.  Cover, title, interaction metrics and the platform share link
 * all come from the stored card; a missing link renders a disabled state rather than a guessed URL.
 */
function VideoCollection({
  title,
  hint,
  collection,
  coverUrl,
}: {
  title: string;
  hint: string;
  collection: FeaturedCollectionView | null;
  coverUrl: (objectId: string) => string;
}) {
  const cards = collection?.cards ?? [];
  return (
    <section className="biz-video-block">
      <div className="biz-subheading">
        <h4>{title}</h4>
        <p>{hint}</p>
        {collection ? <span>{collection.status === "COMPLETE" ? `${cards.length} 条` : collection.status}</span> : null}
      </div>
      {!collection ? (
        <EmptyNote>未取到该集合的观测数据。</EmptyNote>
      ) : cards.length === 0 ? (
        <EmptyNote>
          {collection.status === "EMPTY"
            ? "平台已确认该集合为空（该达人近 30 天内暂无符合条件的作品）。"
            : `该集合暂无作品；集合状态：${collection.status}。`}
        </EmptyNote>
      ) : (
        <div className="biz-video-grid">
          {cards.map((card) => (
            <VideoCard key={card.card_id ?? `${card.position}`} card={card} coverUrl={coverUrl} />
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * 已入库封面的一张卡片。
 *
 * 封面地址指向本项目对象存储的授权端点（不是平台签名外链，后者会过期）。图片加载失败时不把该卡片
 * 永久钉在失败态：先带缓存参数重试一次（覆盖 API 重启、代理瞬时失败等一次性错误），仍失败才降级
 * 为占位。`cover_object_id` 变化时重置全部状态，避免上一张卡片的失败态泄漏到下一张。
 */
function VideoCard({ card, coverUrl }: { card: FeaturedCardView; coverUrl: (objectId: string) => string }) {
  const base = card.cover_status === "STORED" && card.cover_object_id ? coverUrl(card.cover_object_id) : null;
  const [attempt, setAttempt] = useState(0);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    setAttempt(0);
    setMissing(false);
  }, [base]);
  const src = base ? (attempt === 0 ? base : `${base}${base.includes("?") ? "&" : "?"}cover_retry=${attempt}`) : null;
  const stored = Boolean(src) && !missing;
  const link = card.canonical_link || card.link_from_fields;
  const title = card.title?.trim() || "平台未返回标题";
  /**
   * 封面加载失败的处理。
   *
   * 一次失败可能是 API 重启或代理瞬时错误，因此先带参数重试最多两次；若封面端点在重试后仍返回
   * `COVER_NOT_FOUND`，说明该对象在数据库有引用但**对象存储里没有文件**（本机实测存在这类历史
   * 快照），这是数据缺口而不是展示缺陷，必须如实标注为「封面文件缺失」而不是含糊的「加载失败」。
   */
  const onCoverError = async (element: HTMLImageElement) => {
    if (attempt < 2) {
      setAttempt(attempt + 1);
      return;
    }
    let notFound = false;
    try {
      const response = await fetch(element.currentSrc || (src as string), { credentials: "include" });
      if (response.status === 404) {
        const detail = await response.json().catch(() => null);
        notFound = Boolean(detail && String(detail.message || "").includes("COVER_NOT_FOUND"));
      }
    } catch {
      notFound = false;
    }
    if (notFound) setMissing(true);
  };
  return (
    <article className="biz-video-card">
      <div className="biz-cover">
        {stored ? (
          <img
            src={src as string}
            alt=""
            decoding="async"
            onError={(event) => {
              void onCoverError(event.currentTarget);
            }}
          />
        ) : (
          <div className="biz-cover-missing">
            <ImageOff size={18} />
            <span title={missing ? "封面对象在数据库中已登记，但对象存储中没有对应文件；需重新采集该达人才能补齐" : undefined}>
              {missing
                ? "封面文件缺失（需重新采集）"
                : card.cover_status === "FAILED"
                  ? "封面采集失败"
                  : "暂无封面"}
            </span>
          </div>
        )}
        {link ? (
          <a
            className="biz-play"
            href={link}
            target="_blank"
            rel="noreferrer"
            aria-label={`在抖音打开作品：${title}`}
          >
            <span className="biz-play-triangle" aria-hidden="true" />
          </a>
        ) : null}
        <span className="biz-position">{String(card.position + 1).padStart(2, "0")}</span>
      </div>
      <div className="biz-video-copy">
        <strong title={title}>{title}</strong>
        <div className="biz-video-stats">
          <span>播放量 <b>{countValue(card.play)}</b></span>
          <span>点赞量 <b>{countValue(card.like)}</b></span>
          <span>评论量 <b>{countValue(card.comment)}</b></span>
        </div>
        {card.truncated_fields.length ? <em className="biz-truncated">部分字段截断</em> : null}
      </div>
    </article>
  );
}

export function CommercialPanel({
  payload,
  index,
  contents,
}: {
  payload: Record<string, unknown>;
  index: CatalogIndex;
  contents?: FeaturedContent;
}) {
  return (
    <div className="profile-sections biz-sections">
      <ContentDataPanel payload={payload} index={index} />
      <EffortEstimatePanel payload={payload} index={index} />
      {contents ? (
        <>
          <VideoCollection
            title="优秀传播视频"
            hint="数据来源：collections.excellent_reach；播放/点赞/评论为平台原始值，卡片可跳转抖音作品页。"
            collection={contents.reach}
            coverUrl={contents.coverUrl}
          />
          {contents.loading ? <EmptyNote>正在读取精选作品…</EmptyNote> : null}
          {contents.error ? (
            <p className="biz-error">
              精选作品读取失败：{contents.error instanceof Error ? contents.error.message : String(contents.error)}
              <button className="link-button" type="button" onClick={contents.onRetry}>
                重试
              </button>
            </p>
          ) : null}
        </>
      ) : null}
      <SeedingValuePanel payload={payload} index={index} />
      {contents ? (
        <VideoCollection
          title="优秀种草视频"
          hint="数据来源：collections.excellent_seeding；与优秀传播视频使用同一套卡片组件，数据源不同。"
          collection={contents.seeding}
          coverUrl={contents.coverUrl}
        />
      ) : null}
      <ConversionValuePanel payload={payload} index={index} />
    </div>
  );
}
