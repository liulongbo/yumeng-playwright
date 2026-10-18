/**
 * Chapter panels for the creator detail page: 概览 / 商业能力 / 创作能力 / 履约能力.
 *
 * Each panel renders one platform relationship (a record collection, a distribution or a scalar
 * group) instead of flattening a structured field into a single text line.
 */
import { useMemo, useState, type ReactNode } from "react";
import {
  collectionCounts,
  moduleFields,
  type CatalogIndex,
} from "../fieldCatalog";
import {
  countText,
  isBlank,
  unixSecondsText,
} from "../format";
import {
  ChipList,
  DistributionBars,
  EmptyNote,
  FactRow,
  MetricTile,
  Panel,
  RangePill,
  type DistributionItem,
} from "./ui";
import { buildVideoItems, VideoPerformance } from "./videoPerformance";
import { fieldView, periodSuffix, type FieldView } from "./views";
import type { CreatorVideoPage } from "../types";

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function rows(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(record(item)))
    : [];
}

function viewFor(
  payload: Record<string, unknown>,
  index: CatalogIndex,
  moduleKey: string,
  fieldKey: string,
): FieldView {
  return fieldView(payload, index, moduleKey, fieldKey);
}

function stateOf(view: FieldView): ReactNode {
  return <em>{view.state ?? "—"}</em>;
}

/**
 * Every field of one module, labelled from the verified registry.
 *
 * `exclude` holds fields already shown elsewhere on the page (the identity rail or a chart panel) so
 * the same value is not listed twice in the same chapter.
 */
export function ModuleFacts({
  payload,
  index,
  moduleKey,
  title,
  hint,
  exclude = [],
  wide,
  id,
  children,
}: {
  payload: Record<string, unknown>;
  index: CatalogIndex;
  moduleKey: string;
  title: string;
  hint?: ReactNode;
  exclude?: string[];
  wide?: boolean;
  id?: string;
  children?: ReactNode;
}) {
  const fields = moduleFields(payload, moduleKey).filter(
    (field) => !exclude.includes(String(field.field_key ?? "")),
  );
  const counts = collectionCounts(payload, moduleKey);
  return (
    <Panel
      title={title}
      hint={hint}
      wide={wide}
      id={id}
      meta={`${counts.collected}/${counts.total} 已采集`}
    >
      {fields.length ? (
        <dl className="profile-facts">
          {fields.map((field) => {
            const key = String(field.field_key ?? "");
            const view = viewFor(payload, index, moduleKey, key);
            return (
              <FactRow
                key={key}
                label={view.label}
                note={view.note ?? periodSuffix(view)}
                title={typeof view.data === "string" ? view.data : undefined}
                value={view.collected && !view.blank ? view.text : stateOf(view)}
                pending={!view.collected || view.blank}
              />
            );
          })}
        </dl>
      ) : (
        <EmptyNote>该模块本次没有可展示的字段。</EmptyNote>
      )}
      {children}
    </Panel>
  );
}

export function OverviewPanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const RAIL_FIELDS = [
    "nickname",
    "avatar_uri",
    "followers",
    "monthly_deep_users",
    "monthly_follower_growth_rate",
    "creator_type_label",
    "industry_labels",
    "content_theme_labels",
    "introduction",
  ];
  // 该「商业传播表现」条带属于已被 CD-05 取消挂载的「达人概览」章节。注意 `spread.play_median`
  // 是顶层 `play_mid`，**不是**平台上名为「播放量中位数」的那张卡片（后者见 ContentDataPanel
  // 里的 `item_rate_metrics.play_mid`，CD-08 已更正）；这里保留原读取方式仅因该面板当前不渲染，
  // 一旦重新挂载必须同步改成 `item_rate_metrics`。
  const spread = [
    "play_median",
    "average_likes",
    "average_comments",
    "average_shares",
  ].map((key) => viewFor(payload, index, "spread", key));
  const duration = viewFor(payload, index, "spread", "average_duration");
  const playStability = viewFor(payload, index, "spread", "play_stability");
  const itemRate = record(viewFor(payload, index, "spread", "item_rate_metrics").data);
  const marketingTags = viewFor(payload, index, "commercial", "marketing_industry_tags");
  const density = record(viewFor(payload, index, "creation", "content_theme_density").data);
  const densityItems: DistributionItem[] = density
    ? Object.entries(density)
        .map(([label, value]) => {
          const item = record(value) ?? {};
          return {
            label: typeof item.label_name === "string" ? item.label_name : label,
            value: Number(item.label_item_count ?? 0),
          };
        })
        .filter((item) => Number.isFinite(item.value))
        .sort((a, b) => b.value - a.value)
    : [];

  return (
    <div className="profile-sections">
      <div className="profile-grid">
        <ModuleFacts
          payload={payload}
          index={index}
          moduleKey="basic"
          title="达人基础资料"
          hint="其余基础字段；昵称、头像与核心指标在左侧资料卡。"
          exclude={RAIL_FIELDS}
        />
        <Panel title="商业传播表现" hint="平台原始值；平均值与中位数未做单位换算。">
          <div className="metric-strip profile-metrics single-column">
            {spread.map((view) => (
              <MetricTile
                key={view.fieldKey}
                label={view.label}
                value={view.collected && !view.blank ? view.text : "—"}
                detail={view.collected && !view.blank ? undefined : view.state ?? undefined}
                pending={!view.collected || view.blank}
              />
            ))}
            <MetricTile
              label={duration.label}
              value={
                duration.collected && !duration.blank
                  ? `${(Number(duration.data) / 100).toFixed(1)} 秒`
                  : "—"
              }
              detail={
                duration.collected && !duration.blank
                  ? `平台原值 ${duration.data}（秒×100）`
                  : duration.state ?? undefined
              }
              pending={!duration.collected || duration.blank}
            />
          </div>
          <dl className="profile-facts compact">
            <FactRow
              label="播放稳定性"
              value={
                playStability.collected && !playStability.blank ? playStability.text : stateOf(playStability)
              }
              note={
                playStability.collected && !playStability.blank
                  ? "平台返回标签而非指标"
                  : undefined
              }
              pending={!playStability.collected || playStability.blank}
            />
            <FactRow
              label="作品传播比较指标"
              value={
                itemRate && "play_mid" in itemRate
                  ? `作品数 ${countText(record(itemRate.item_num)?.value ?? null)} · 中位播放 ${countText(
                      record(itemRate.play_mid)?.value ?? null,
                    )}（同行超越 ${String(record(itemRate.play_mid)?.overtake ?? "—")}）`
                  : "—"
              }
              pending={!itemRate || !("play_mid" in itemRate)}
            />
          </dl>
        </Panel>
      </div>
      <div className="profile-grid">
        <Panel
          title="商业合作行业标签"
          hint="平台按「一级行业-二级行业」返回。"
          meta={marketingTags.collected ? undefined : marketingTags.state ?? undefined}
        >
          <div className="panel-chips">
            <ChipList
              items={
                Array.isArray(marketingTags.data)
                  ? (marketingTags.data as unknown[]).map((item) => String(item))
                  : []
              }
              empty="平台未返回商业合作行业标签。"
            />
          </div>
        </Panel>
        <Panel
          title="内容主题集中度"
          hint="平台按主题统计的作品条数；占比为本页按条数计算的展示值。"
          meta={densityItems.length ? `${densityItems.length} 个主题` : undefined}
        >
          <DistributionBars items={densityItems} ariaLabel="内容主题集中度" />
        </Panel>
      </div>
    </div>
  );
}

interface OfferView {
  desc: string;
  price: string;
  originPrice: string;
  settlement: string;
  validity: string;
  status: string;
}

function offerViews(data: unknown): OfferView[] {
  return rows(data).map((offer) => {
    const start = unixSecondsText(offer.start_time);
    const end = unixSecondsText(offer.end_time);
    const open = offer.is_open === true || offer.enable === true;
    return {
      desc: typeof offer.desc === "string" ? offer.desc : String(offer.field ?? "未标记合作形式"),
      price:
        offer.price === null || offer.price === undefined ? "—" : `￥${countText(offer.price)}`,
      originPrice:
        offer.origin_price === null || offer.origin_price === undefined
          ? "—"
          : `￥${countText(offer.origin_price)}`,
      settlement: typeof offer.settlement_desc === "string" ? offer.settlement_desc : "—",
      validity: start === "—" && end === "—" ? "—" : `${start} 起至 ${end}`,
      status: open ? "开放" : "关闭",
    };
  });
}

export function QuoteTable({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const view = viewFor(payload, index, "commercial", "cooperation_offers");
  const offers = view.collected ? offerViews(view.data) : [];
  return (
    <Panel
      title="合作形式与报价明细"
      hint="平台一次返回多项合作形式；金额按平台展示币种标注（人民币 ￥），不做换算。"
      meta={offers.length ? `${offers.length} 项` : view.state ?? undefined}
      wide
      id="quotes"
    >
      {offers.length ? (
        <div className="quote-table">
          <div className="quote-head">
            <span>合作形式</span>
            <span>结算说明</span>
            <span>报价</span>
            <span>原价</span>
            <span>有效期</span>
            <span>状态</span>
          </div>
          {offers.map((offer, position) => (
            <div key={`${offer.desc}-${position}`}>
              <strong>{offer.desc}</strong>
              <span>{offer.settlement}</span>
              <b>{offer.price}</b>
              <span>{offer.originPrice}</span>
              <span>{offer.validity}</span>
              <span className={offer.status === "开放" ? "ok" : "off"}>{offer.status}</span>
            </div>
          ))}
        </div>
      ) : (
        <EmptyNote>{view.collected ? "本次快照没有报价项。" : view.state}</EmptyNote>
      )}
    </Panel>
  );
}

/**
 * 「创作能力」章节。
 *
 * 视频表现来自独立存储的作品观测（DATA-02）：调用方按入口把 `videos` 页面传进来（任务入口读本任务
 * 快照的观测，达人库入口读该达人当前快照的观测），本组件只按当前选中的集合过滤并归一化。快照 JSONB
 * 里的两个视频字段不再参与图表与列表，避免封面/链接两处不一致；其余创作能力字段（内容类型分布、
 * 评论热词）仍从快照读取。
 */
export function CreationPanel({
  payload,
  index,
  featured,
  videos,
  videosLoading,
  videosError,
  onRetryVideos,
  coverUrl,
}: {
  payload: Record<string, unknown>;
  index: CatalogIndex;
  featured?: ReactNode;
  /** 两个集合的作品观测；缺失时为 null，页面按空集降级。 */
  videos?: CreatorVideoPage | null;
  videosLoading?: boolean;
  videosError?: unknown;
  onRetryVideos?: () => void;
  /** 该入口的授权封面端点构造器；不构造平台 CDN 地址。 */
  coverUrl: (objectId: string) => string;
}) {
  const [kind, setKind] = useState<"recent_video_performance" | "recent_xingtu_video_performance">(
    "recent_video_performance",
  );
  // CD-05 / DATA-02：柱状图与下方作品列表共用同一份规范化数据，避免两处数值/封面/链接不一致。
  const items = useMemo(() => {
    const rows = Array.isArray(videos?.items) ? videos.items : [];
    return buildVideoItems(rows.filter((item) => item.module_key === kind));
  }, [videos, kind]);

  const contentDistribution = rows(viewFor(payload, index, "creation", "video_content_distribution").data);
  const contentItems: DistributionItem[] = contentDistribution
    .map((item) => ({
      label: typeof item.name === "string" ? item.name : String(item.id ?? "未命名"),
      value: Number(item.cnt ?? 0),
      display: `${Number(item.proportion ?? 0) ? `${(Number(item.proportion) * 100).toFixed(1)}%` : "—"} · ${
        Number(item.cnt ?? 0).toLocaleString("zh-CN")
      } 条`,
    }))
    .sort((a, b) => b.value - a.value);

  const tokens = rows(viewFor(payload, index, "creation", "hot_comment_tokens").data);
  const tokenItems: DistributionItem[] = tokens.map((token) => ({
    label: String(token.comment_token ?? "未命名"),
    value: Number(token.hot_rate ?? 0),
    display: Number(token.hot_rate ?? 0).toLocaleString("zh-CN"),
  }));

  const videoStatus = videosLoading
    ? "读取中"
    : videosError
      ? "读取失败"
      : "平台未返回作品记录";

  return (
    <div className="profile-sections">
      {featured}
      <Panel
        title="最新视频表现"
        hint="每根柱子对应一条真实视频作品，柱高与标签取该作品真实播放量；X 轴为平台返回的发布时间。点击柱或作品卡片在新标签页打开抖音作品页。"
        wide
        id="content"
        meta={items.length ? `${items.length} 条` : videoStatus}
      >
        <div className="profile-controls">
          <div>
            <button className={kind === "recent_video_performance" ? "active" : ""} onClick={() => setKind("recent_video_performance")}>
              最新视频
            </button>
            <button
              className={kind === "recent_xingtu_video_performance" ? "active" : ""}
              onClick={() => setKind("recent_xingtu_video_performance")}
            >
              最新星图视频
            </button>
          </div>
        </div>
        {items.length ? (
          <VideoPerformance items={items} coverUrl={coverUrl} />
        ) : videosLoading ? (
          <EmptyNote>正在读取作品观测…</EmptyNote>
        ) : videosError ? null : (
          <EmptyNote>本次没有视频记录。</EmptyNote>
        )}
        {videosError ? (
          <p className="biz-error">
            作品观测读取失败：{videosError instanceof Error ? videosError.message : String(videosError)}
            {onRetryVideos ? (
              <button className="link-button" type="button" onClick={onRetryVideos}>
                重试
              </button>
            ) : null}
          </p>
        ) : null}
      </Panel>

      <div className="profile-grid">
        <Panel
          title="视频内容类型分布"
          hint="平台按内容类型统计的作品条数与占比。"
          meta={contentItems.length ? `${contentItems.length} 类` : undefined}
        >
          <DistributionBars items={contentItems} ariaLabel="视频内容类型分布" />
        </Panel>
        <Panel
          title="评论热词"
          hint="平台热词热度值（hot_rate），按原值排序。"
          meta={tokenItems.length ? `${tokenItems.length} 个` : undefined}
        >
          <DistributionBars items={tokenItems} ariaLabel="评论热词" />
        </Panel>
      </div>
    </div>
  );
}

/**
 * 履约能力章节。
 *
 * CD-06 需求调整：移除「行业订单分布」「行业播放分布」「合作行业分布」三个模块的页面展示
 * （纯展示层移除；`fulfillment.industry_order_distribution` / `industry_play_distribution` /
 * `cooperation_industry_distribution` 的数据、API 与字段观测均未改动，仍可在字段来源抽屉查看）。
 * 本节只保留「履约与合作表现」。
 */
export function FulfillmentPanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const scores = [
    "credit_score",
    "new_credit_score",
    "historical_order_count",
    "processing_order_count",
    "max_processing_order_count",
    "message_reply_rate",
  ].map((key) => viewFor(payload, index, "fulfillment", key));

  return (
    <div className="profile-sections">
      <Panel
        title="履约与合作表现"
        hint="信用分、订单数与回复率为平台原始值；比例口径未登记。"
        id="fulfillment"
      >
        <div className="metric-strip profile-metrics single-column">
          {scores.map((view) => (
            <MetricTile
              key={view.fieldKey}
              label={view.label}
              value={view.collected && !view.blank ? view.text : "—"}
              detail={view.collected && !view.blank ? undefined : view.state ?? undefined}
              pending={!view.collected || view.blank}
            />
          ))}
        </div>
      </Panel>
    </div>
  );
}
