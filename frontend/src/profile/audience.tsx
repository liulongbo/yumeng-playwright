/**
 * 连接用户 chapter plus the data-quality/provenance drawer.
 *
 * CD-06 需求调整（见 docs/tasks/CD-06.md）：移除「连接用户规模与粉丝增长」面板与「近 30 日粉丝日增量」，
 * 并把「近 30 日粉丝总数」与「近 30 日连接用户（平台窗口口径）」合并为**一张双轴趋势图**——左轴连接用户数、
 * 右轴粉丝数、X 轴时间，Hover 任一时间点同时查看两者。两条线仍是两个不同的平台口径，各自独立取值与独立
 * 量纲，只是共用一条时间轴；不相加、不归一化、不互相推算。
 *
 * The remaining daily series are different platform facts:
 *
 * - `fans.fans_daily_trend`  — daily follower total (source request `get_author_daily_fans`);
 * - `fans.connection_daily_trend` — the platform's connected-user window, whose last point equals
 *   the registered monthly connected-user metric.
 *
 * `fans.connection_funnel` and `seeding.seeding_link_structure` are drawn as a partition with an
 * explicit total, never as a funnel: stages 1–4 sum exactly to stage 5 in every stored snapshot, and
 * stage 5 is the same number as `fans.monthly_connected_users`.
 */
import { useState } from "react";
import { Database, Info, X } from "lucide-react";
import {
  collectionCounts,
  moduleRows,
  moduleStatus,
  type CatalogIndex,
} from "../fieldCatalog";
import {
  countText,
  moduleStatusTone,
  unixSecondsText,
} from "../format";
import { DistributionBars, DualAxisTrend, EmptyNote, FactRow, LayerStack, Panel, type ChartPoint, type LayerItem, type TrendSeries } from "./ui";
import { fieldView } from "./views";
import type { FieldView } from "./views";

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function series(value: unknown, key: string): ChartPoint[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const point = record(item);
      if (!point) return null;
      const raw = point[key];
      const amount = Number(raw);
      if (!Number.isFinite(amount)) return null;
      return { label: String(point.date ?? ""), value: amount };
    })
    .filter((point): point is ChartPoint => Boolean(point));
}

/**
 * The platform's own names for the four layers, read from the live 巨量星图 creator homepage on
 * 2026-10-14: 了解 / 兴趣 / 喜欢 / 追随, with the fifth value shown as 连接用户数 (their total).
 */
const CONNECTED_USER_LAYERS: Record<string, string> = {
  "1": "了解",
  "2": "兴趣",
  "3": "喜欢",
  "4": "追随",
};

/** Stage labels are registered by the platform for the four layers; anything else keeps its code. */
function stageLayers(
  funnel: unknown,
  structure: unknown,
): { layers: LayerItem[]; total: LayerItem } | null {
  const funnelRecord = record(funnel);
  if (!funnelRecord) return null;
  const structureRecord = record(structure) ?? {};
  const keys = Object.keys(funnelRecord).sort();
  const layers: LayerItem[] = [];
  let total: LayerItem | null = null;
  for (const key of keys) {
    const item = record(funnelRecord[key]) ?? {};
    const value = Number(item.value ?? NaN);
    if (!Number.isFinite(value)) continue;
    const comparison = record(structureRecord[key]) ?? {};
    const median = comparison.same_industry_median;
    const rank = comparison.rank_percent;
    const comparisonText =
      median !== undefined
        ? `同行业中位 ${countText(median)}`
        : rank !== undefined
          ? `平台超越比例原值 ${Number(rank)}`
          : item.relative_ratio !== undefined
            ? `相对比率 ${Number(item.relative_ratio)}`
            : undefined;
    const entry: LayerItem = {
      key,
      label: CONNECTED_USER_LAYERS[key] ?? `平台阶段 ${key}`,
      value,
      comparison: comparisonText,
    };
    if (key === keys[keys.length - 1] && keys.length > 1) total = entry;
    else layers.push(entry);
  }
  if (!total) return null;
  return { layers, total };
}

function AudienceDistribution({ view }: { view: FieldView }) {
  const groups = Array.isArray(view.data) ? (view.data as unknown[]).map(record).filter(Boolean) : [];
  const [active, setActive] = useState(0);
  if (!groups.length) return <EmptyNote>{view.state ?? "平台未返回画像分布。"}</EmptyNote>;
  const group = groups[Math.min(active, groups.length - 1)] ?? {};
  const list = Array.isArray(group.distribution_list)
    ? (group.distribution_list as unknown[]).map(record).filter(Boolean)
    : [];
  const items = list.map((item) => {
    const item2 = item ?? {};
    return {
      label: String(item2.distribution_key ?? "未命名"),
      value: Number(item2.distribution_value ?? 0),
      display: Number(item2.distribution_value ?? 0).toLocaleString("zh-CN"),
    };
  });
  return (
    <>
      <div className="profile-controls">
        {groups.map((item, position) => (
          <button
            key={String(item?.type ?? position)}
            className={position === active ? "active" : ""}
            onClick={() => setActive(position)}
          >
            {String(item?.type_display ?? item?.type ?? `画像 ${position + 1}`)}
          </button>
        ))}
      </div>
      {group?.description ? <p className="audience-summary">{String(group.description)}</p> : null}
      <DistributionBars
        items={items}
        ariaLabel={`连接用户画像：${String(group?.type_display ?? "分布")}`}
        note="占比为本页按该分布组人数计算的展示值。"
      />
    </>
  );
}

export function AudiencePanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const funnel = fieldView(payload, index, "fans", "connection_funnel");
  const structure = fieldView(payload, index, "fans", "seeding_link_structure");
  const stacked = stageLayers(funnel.data, structure.data);

  const followerTotal = fieldView(payload, index, "fans", "fans_daily_trend");
  const connectionTrend = fieldView(payload, index, "fans", "connection_daily_trend");
  const audience = fieldView(payload, index, "fans", "audience_distributions");
  const audienceUpdated = fieldView(payload, index, "fans", "audience_last_updated_at");

  const followerPoints = series(followerTotal.data, "fans_cnt");
  const connectionPoints = series(connectionTrend.data, "value");

  /**
   * 两条平台序列各自独立取值：左轴连接用户数（平台窗口口径）、右轴粉丝数。
   * 量纲差异很大（本达人约 2.3–5.0 千万 vs 约 135 万），因此各用各的刻度，不做归一化。
   */
  const trends: TrendSeries[] = [
    {
      key: "connection",
      label: "连接用户数",
      points: connectionPoints,
      axis: "left",
      tone: "blue",
      format: (value) => countText(value),
    },
    {
      key: "followers",
      label: "粉丝数",
      points: followerPoints,
      axis: "right",
      tone: "crimson",
      format: (value) => countText(value),
    },
  ];
  const trendPoints = connectionPoints.length + followerPoints.length;

  return (
    <div className="profile-sections">
      <Panel
        title="连接用户分层与同行业对比"
        hint="平台把该结构标为「连接用户漏斗」，实际为四层互斥分层 + 合计；分层名称与合计口径均按平台页面呈现。"
        wide
        id="audience"
        meta={stacked ? `${stacked.layers.length} 层 + 合计` : funnel.state ?? undefined}
      >
        {stacked ? (
          <LayerStack
            layers={stacked.layers}
            total={stacked.total}
            totalLabel="连接用户数（合计）"
            ariaLabel="连接用户分层结构"
            note={
              structure.collected
                ? "对比列为平台返回的同行业中位数/超越比例原值。"
                : "本次未取到种草链路层级的同行业对比数据。"
            }
          />
        ) : (
          <EmptyNote>{funnel.state ?? "平台未返回连接用户分层数据。"}</EmptyNote>
        )}
      </Panel>
      <Panel
        title="近 30 日连接用户与粉丝趋势"
        hint="左轴为连接用户数（平台窗口口径，末点=月连接用户数，不是日增量、不可求和），右轴为粉丝总数；两条线各用各的刻度，鼠标移到任一日期可同时查看两者。"
        wide
        meta={trendPoints ? `${trendPoints} 点` : connectionTrend.state ?? followerTotal.state ?? undefined}
      >
        <DualAxisTrend
          series={trends}
          ariaLabel="近30日连接用户数与粉丝数双轴趋势"
          note="左轴连接用户数 · 右轴粉丝数"
        />
      </Panel>
      <Panel
        title="连接用户画像"
        hint="平台按画像类型返回人数分布，共 8 类。"
        wide
        meta={
          audience.collected
            ? `更新时间 ${unixSecondsText(audienceUpdated.data)}`
            : audience.state ?? undefined
        }
      >
        <AudienceDistribution view={audience} />
      </Panel>
    </div>
  );
}

export function ProvenanceDrawer({
  open,
  onClose,
  payload,
  index,
  moduleStatuses,
  fieldSources,
  collectedCount,
  failedCount,
}: {
  open: boolean;
  onClose: () => void;
  payload: Record<string, unknown>;
  index: CatalogIndex;
  moduleStatuses: Record<string, string | null>;
  fieldSources: Record<string, unknown>;
  collectedCount: number;
  failedCount: number;
}) {
  if (!open) return null;
  const totals = collectionCounts(payload);
  return (
    <div className="provenance-overlay" role="dialog" aria-modal="true" aria-label="数据质量与字段来源">
      <div className="provenance-sheet">
        <div className="provenance-head">
          <div>
            <h2>数据质量与字段来源</h2>
            <p>
              已采集 {collectedCount} · 采集失败 {failedCount} · 页面可读字段 {totals.collected}/
              {totals.total}
            </p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭数据来源">
            <X size={16} />
          </button>
        </div>
        <p className="provenance-note">
          <Info size={13} />
          展示的是平台原始字段：状态、单位、周期与观测时间均来自字段级观测，不做换算。
        </p>
        <div className="module-statuses">
          {Object.keys(payload.modules ?? {}).map((moduleKey) => (
            <span
              key={moduleKey}
              className={`module-status ${moduleStatusTone(moduleStatuses[moduleKey] ?? moduleStatus(payload, moduleKey))}`}
            >
              {moduleKey}：{moduleStatuses[moduleKey] ?? moduleStatus(payload, moduleKey)}
            </span>
          ))}
        </div>
        {Object.keys(payload.modules ?? {}).map((moduleKey) => (
          <section key={moduleKey} className="provenance-module">
            <h3>{moduleKey}</h3>
            <dl className="provenance-facts">
              {moduleRows(payload, index, moduleKey).map((row) => {
                const source = record(fieldSources[row.fieldKey]) ?? {};
                const status = String(row.field?.status ?? source.status ?? "MISSING_SOURCE");
                return (
                  <div key={`${moduleKey}.${row.fieldKey}`}>
                    <dt>
                      {row.label}
                      <small>{row.fieldKey}</small>
                    </dt>
                    <dd>
                      <b>{status}</b>
                      <span>{row.entry?.unit ? `单位 ${row.entry.unit}` : "单位未登记"}</span>
                      <span>{row.entry?.period_label ? `周期 ${row.entry.period_label}` : "周期未登记"}</span>
                      <span>
                        {String(
                          row.field?.observed_at ?? source.observed_at ?? "无观测时间",
                        )}
                      </span>
                      <span>
                        来源{" "}
                        {String(row.field?.source_kind ?? source.source_kind ?? "未登记")}
                        {row.entry?.name_source === "evidence_correction"
                          ? " · 名称按实测数据源修正"
                          : ""}
                      </span>
                    </dd>
                  </div>
                );
              })}
            </dl>
          </section>
        ))}
        <p className="provenance-note">
          <Database size={13} />
          原始 JSONB 仍为权威来源；本页只做只读展示，不写回任何快照或索引。
        </p>
      </div>
    </div>
  );
}

export { FactRow };
