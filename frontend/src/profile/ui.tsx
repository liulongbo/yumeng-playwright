/**
 * Presentational primitives and charts for the creator detail page.
 *
 * Every chart here renders exactly one platform relationship; none of them infers a unit, a scale
 * or a cross-field meaning.  Charts are plain SVG/CSS: the product has no chart dependency and the
 * existing detail view already drew its bars with CSS.
 */
import { useMemo, useState, type MouseEvent, type ReactNode } from "react";

export interface ChartPoint {
  label: string;
  value: number;
}

/** One named series of a dual-axis chart; values are the platform's own raw numbers. */
export interface TrendSeries {
  key: string;
  label: string;
  points: ChartPoint[];
  /** Which vertical axis this series is measured against. */
  axis: "left" | "right";
  tone: "blue" | "crimson";
  /** Exact tooltip text for one value; the axis label uses `wanAxisText` instead. */
  format: (value: number) => string;
}

/**
 * A count shown on a chart axis: 「万」 with one decimal, matching this page's other count units.
 *
 * Axis text stays short on purpose (`2,344.0万` rather than `23,439,854`). Values below 10,000 keep
 * their plain form so a small series is not flattened to `0.0万`. Display only — the raw platform
 * number is what the chart is drawn from and what the tooltip prints.
 */
function wanAxisText(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  if (magnitude >= 10_000) return `${(magnitude / 10_000).toFixed(1)}万`;
  return magnitude.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

interface DualAxisDatum {
  index: number;
  date: string;
  x: number;
  y: number;
  value: number;
}


export function Panel({
  title,
  hint,
  meta,
  wide,
  id,
  children,
}: {
  title: string;
  hint?: ReactNode;
  meta?: ReactNode;
  wide?: boolean;
  id?: string;
  children: ReactNode;
}) {
  return (
    <section className={`profile-panel${wide ? " wide-profile-panel" : ""}`} id={id}>
      <div className="profile-heading">
        <div>
          <h3>{title}</h3>
          {hint ? <p>{hint}</p> : null}
        </div>
        {meta ? <span>{meta}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="profile-empty">{children}</p>;
}

/** One labelled fact row; `title` keeps the untruncated platform value reachable. */
export function FactRow({
  label,
  value,
  title,
  note,
  pending,
}: {
  label: string;
  value: ReactNode;
  title?: string;
  note?: string;
  pending?: boolean;
}) {
  return (
    <div>
      <dt>
        {label}
        {note ? <small> · {note}</small> : null}
      </dt>
      <dd className={pending ? "pending" : undefined}>
        <span title={title}>{value}</span>
      </dd>
    </div>
  );
}

export function ChipList({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <span className="chip-empty">{empty}</span>;
  return (
    <span className="chip-list">
      {items.map((item, index) => (
        <em key={`${item}-${index}`}>{item}</em>
      ))}
    </span>
  );
}

export function MetricTile({
  label,
  value,
  detail,
  accent = "",
  pending,
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  accent?: string;
  pending?: boolean;
}) {
  return (
    <div className={`metric ${accent}${pending ? " metric-pending" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

/** A platform comparison number, always shown with its own label and as a platform raw value. */
export function RankBar({
  label = "同行超越",
  value,
  note,
}: {
  label?: string;
  value: string;
  note: string;
}) {
  return (
    <span className="rank-bar" title={note}>
      <i>{label}</i>
      <b>{value}</b>
      <small>平台原值</small>
    </span>
  );
}

function scalePoints(points: ChartPoint[]): { min: number; max: number } {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  return { min, max: max === min ? min + 1 : max };
}

/** Line/area chart for a platform-built daily series (30 points, one value per date). */
export function TrendLine({
  points,
  ariaLabel,
  note,
}: {
  points: ChartPoint[];
  ariaLabel: string;
  note?: string;
}) {
  if (points.length < 2) return <EmptyNote>该趋势没有可绘制的数据点。</EmptyNote>;
  const width = 720;
  const height = 190;
  const padding = { top: 16, right: 14, bottom: 22, left: 54 };
  const { min, max } = scalePoints(points);
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const x = (index: number) =>
    padding.left + (points.length === 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = (value: number) => padding.top + innerHeight - ((value - min) / (max - min)) * innerHeight;
  const line = points.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const area = `${padding.left},${padding.top + innerHeight} ${line} ${padding.left + innerWidth},${padding.top + innerHeight}`;
  return (
    <figure className="chart-figure">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel} preserveAspectRatio="none">
        <polygon className="trend-area" points={area} />
        <polyline className="trend-line" points={line} />
        <line className="trend-axis" x1={padding.left} y1={padding.top + innerHeight} x2={padding.left + innerWidth} y2={padding.top + innerHeight} />
        <text className="trend-tick" x={4} y={padding.top + 6}>{max.toLocaleString("zh-CN")}</text>
        <text className="trend-tick" x={4} y={padding.top + innerHeight}>{min.toLocaleString("zh-CN")}</text>
        <text className="trend-tick" x={padding.left} y={height - 6}>{points[0].label}</text>
        <text className="trend-tick end" x={padding.left + innerWidth} y={height - 6}>{points[points.length - 1].label}</text>
      </svg>
      <figcaption>
        {note ? `${note} · ` : ""}
        末值 {points[points.length - 1].value.toLocaleString("zh-CN")}（{points[points.length - 1].label}）
      </figcaption>
    </figure>
  );
}

/**
 * Two platform series drawn on one time axis with **independent** left/right scales (CD-06).
 *
 * 粉丝数 and 连接用户数 are two different platform quantities measured on very different
 * magnitudes (≈1.35 million vs ≈23–50 million here), so a single shared axis would flatten the
 * follower line. Each series therefore keeps its own registered scale and its own axis, and the two
 * are never added, subtracted or normalised into each other.
 *
 * The two series are aligned on a merged, sorted date axis. A series only contributes points for the
 * dates it actually has: the platform returns slightly different windows (for example 09-14…10-13
 * for the follower total and 09-13…10-12 for the connection window), so missing dates stay gaps
 * instead of being filled with a fabricated value.
 *
 * Hovering any date shows both quantities at that date — the interaction the reference page uses.
 */
export function DualAxisTrend({
  series,
  ariaLabel,
  note,
}: {
  series: TrendSeries[];
  ariaLabel: string;
  note?: string;
}) {
  const [hovered, setHovered] = useState<{ index: number; left: number; top: number } | null>(null);

  const timeline = useMemo(() => {
    const dates = new Set<string>();
    for (const item of series) for (const point of item.points) dates.add(point.label);
    return Array.from(dates).sort();
  }, [series]);

  const width = 720;
  const height = 200;
  const padding = { top: 18, right: 62, bottom: 24, left: 62 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;

  const scales = useMemo(() => {
    const computed: Record<string, { min: number; max: number }> = {};
    for (const item of series) {
      const values = item.points.map((point) => point.value);
      const min = values.length ? Math.min(...values) : 0;
      const max = values.length ? Math.max(...values) : 1;
      // A flat series must still get a drawable band rather than a division by zero.
      computed[item.key] = max === min ? { min: min - Math.abs(min || 1) * 0.1, max: max + Math.abs(max || 1) * 0.1 } : { min, max };
    }
    return computed;
  }, [series]);

  if (timeline.length < 2 || series.every((item) => item.points.length < 1)) {
    return <EmptyNote>该趋势没有可绘制的数据点。</EmptyNote>;
  }

  const xAt = (index: number) =>
    padding.left + (timeline.length === 1 ? innerWidth / 2 : (index / (timeline.length - 1)) * innerWidth);
  const yAt = (value: number, key: string) => {
    const { min, max } = scales[key];
    const span = max - min || 1;
    return padding.top + innerHeight - ((value - min) / span) * innerHeight;
  };

  /** Each series' own datapoints, aligned to the shared index so both axes stay comparable. */
  const drawn = series.map((item) => {
    const byDate = new Map(item.points.map((point) => [point.label, point.value]));
    const data: DualAxisDatum[] = timeline.flatMap((date, index) => {
      const value = byDate.get(date);
      if (value === undefined) return [];
      return [{ index, date, x: xAt(index), y: yAt(value, item.key), value }];
    });
    return { item, data };
  });

  const dateTicks = timeline.filter(
    (_, index) => index === 0 || index === timeline.length - 1 || index % Math.ceil(timeline.length / 6) === 0,
  );

  const activeIndex = hovered?.index ?? null;
  const activeDate = activeIndex === null ? null : timeline[activeIndex];

  const handleMove = (event: MouseEvent<SVGRectElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    // Fall back to the rendered width when the band has no measured box (for example while the panel
    // is not laid out); the index is then still derived from the same viewBox geometry.
    const rectWidth = event.currentTarget.width?.baseVal?.value ?? 0;
    const span = box.width || rectWidth || innerWidth;
    const ratio = span ? (event.clientX - box.left) / span : 0;
    const index = Math.max(0, Math.min(timeline.length - 1, Math.round(ratio * (timeline.length - 1))));
    setHovered({ index, left: event.clientX, top: event.clientY - 14 });
  };

  return (
    <figure className="chart-figure">
      {/* Legend, as on the reference page: one entry per series, in its own colour. */}
      <div className="trend-legend">
        {series.map((item) => (
          <span key={`legend-${item.key}`} className={`tone-${item.tone}`}>
            <i />
            {item.label}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel} preserveAspectRatio="none">
        {[0, 0.5, 1].map((ratio) => (
          <line
            key={ratio}
            className="trend-gridline"
            x1={padding.left}
            y1={padding.top + innerHeight * ratio}
            x2={padding.left + innerWidth}
            y2={padding.top + innerHeight * ratio}
          />
        ))}
        {series.map((item) => {
          const { min, max } = scales[item.key];
          const anchor = item.axis === "left" ? "start" : "end";
          const axisX = item.axis === "left" ? 4 : width - 4;
          return (
            <g key={`axis-${item.key}`}>
              <text className="trend-axis-title" x={axisX} y={padding.top - 6} textAnchor={anchor}>
                {item.label}
              </text>
              <text className="trend-tick" x={axisX} y={padding.top + 6} textAnchor={anchor}>
                {wanAxisText(max)}
              </text>
              <text className="trend-tick" x={axisX} y={padding.top + innerHeight} textAnchor={anchor}>
                {wanAxisText(min)}
              </text>
            </g>
          );
        })}
        {drawn.map(({ item, data }) => (
          <g key={`series-${item.key}`}>
            <polyline
              className={`trend-line tone-${item.tone}`}
              points={data.map((point) => `${point.x},${point.y}`).join(" ")}
            />
            {data.map((point) => (
              <circle
                key={point.date}
                className={`trend-dot tone-${item.tone}`}
                cx={point.x}
                cy={point.y}
                r={activeIndex === point.index ? 3.5 : 1.6}
              />
            ))}
          </g>
        ))}
        {activeIndex !== null ? (
          <g className="trend-guide">
            <line
              x1={xAt(activeIndex)}
              y1={padding.top}
              x2={xAt(activeIndex)}
              y2={padding.top + innerHeight}
            />
            {drawn.map(({ item, data }) => {
              const point = data.find((entry) => entry.index === activeIndex);
              return point ? (
                <circle key={`active-${item.key}`} className={`trend-dot active tone-${item.tone}`} cx={point.x} cy={point.y} r={4} />
              ) : null;
            })}
          </g>
        ) : null}
        <line className="trend-axis" x1={padding.left} y1={padding.top + innerHeight} x2={padding.left + innerWidth} y2={padding.top + innerHeight} />
        {dateTicks.map((date) => (
          <text
            key={date}
            className="trend-tick"
            x={xAt(timeline.indexOf(date))}
            y={height - 6}
            textAnchor="middle"
          >
            {date}
          </text>
        ))}
        {/* Transparent capture band: hovering a date shows both quantities at that date. */}
        <rect
          className="trend-capture"
          x={padding.left}
          y={padding.top}
          width={innerWidth}
          height={innerHeight}
          onMouseMove={handleMove}
          onMouseLeave={() => setHovered(null)}
        />
      </svg>
      {hovered && activeDate ? (
        <div
          className="trend-tip"
          role="tooltip"
          style={{ left: hovered.left, top: hovered.top }}
        >
          <b>{activeDate}</b>
          {drawn.map(({ item, data }) => {
            const point = data.find((entry) => entry.index === hovered.index);
            return (
              <span key={`tip-${item.key}`} className={`tone-${item.tone}`}>
                <i />
                {item.label}
                <em>{point ? item.format(point.value) : "该日无数据"}</em>
              </span>
            );
          })}
        </div>
      ) : null}
      <figcaption>
        {note ? `${note} · ` : ""}
        {series
          .map((item) => (item.points.length ? `${item.label} 末值 ${item.format(item.points[item.points.length - 1].value)}（${item.points[item.points.length - 1].label}）` : `${item.label} 无数据`))
          .join(" · ")}
      </figcaption>
    </figure>
  );
}

/** Column chart with a zero baseline; negative platform values render below it. */
export function DeltaBars({ points, ariaLabel, note }: { points: ChartPoint[]; ariaLabel: string; note?: string }) {
  if (!points.length) return <EmptyNote>该趋势没有可绘制的数据点。</EmptyNote>;
  const width = 720;
  const height = 170;
  const padding = { top: 14, right: 12, bottom: 22, left: 52 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const max = Math.max(...points.map((point) => point.value), 0);
  const min = Math.min(...points.map((point) => point.value), 0);
  const span = max - min || 1;
  const zeroY = padding.top + ((max - 0) / span) * innerHeight;
  const slot = innerWidth / points.length;
  const barWidth = Math.max(2, Math.min(14, slot * 0.62));
  const negatives = points.filter((point) => point.value < 0).length;
  return (
    <figure className="chart-figure">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel} preserveAspectRatio="none">
        {points.map((point, index) => {
          const valueY = padding.top + ((max - point.value) / span) * innerHeight;
          const top = Math.min(valueY, zeroY);
          const barHeight = Math.max(1, Math.abs(valueY - zeroY));
          return (
            <rect
              key={`${point.label}-${index}`}
              className={point.value < 0 ? "delta-bar negative" : "delta-bar"}
              x={padding.left + index * slot + (slot - barWidth) / 2}
              y={top}
              width={barWidth}
              height={barHeight}
            >
              <title>{`${point.label}：${point.value.toLocaleString("zh-CN")}`}</title>
            </rect>
          );
        })}
        <line className="trend-axis" x1={padding.left} y1={zeroY} x2={padding.left + innerWidth} y2={zeroY} />
        <text className="trend-tick" x={4} y={padding.top + 6}>{max.toLocaleString("zh-CN")}</text>
        <text className="trend-tick" x={4} y={zeroY + 4}>0</text>
        <text className="trend-tick" x={padding.left} y={height - 6}>{points[0].label}</text>
        <text className="trend-tick end" x={padding.left + innerWidth} y={height - 6}>{points[points.length - 1].label}</text>
      </svg>
      <figcaption>
        {note ? `${note} · ` : ""}
        区间内净增合计 {points.reduce((total, point) => total + point.value, 0).toLocaleString("zh-CN")}
        {negatives ? `，其中 ${negatives} 天为负增长` : ""}
      </figcaption>
    </figure>
  );
}

export interface DistributionItem {
  label: string;
  value: number;
  display?: string;
  hint?: string;
  /**
   * The share shown next to the bar.  Omitted means "share of the group total"; an explicit `null`
   * means the platform already returned a proportion (for example `rate`) and computing a second
   * share would invent a different number.
   */
  share?: number | null;
}

/** Horizontal bars with the item's share of the group; optionally overlays a comparison value. */
export function DistributionBars({
  items,
  ariaLabel,
  note,
  compareLabel,
}: {
  items: DistributionItem[];
  ariaLabel: string;
  note?: string;
  compareLabel?: string;
}) {
  if (!items.length) return <EmptyNote>该分布没有可展示的记录。</EmptyNote>;
  const total = items.reduce((sum, item) => sum + Math.max(0, item.value), 0);
  const max = Math.max(...items.map((item) => item.value), 1);
  return (
    <div className="distribution-list" role="img" aria-label={ariaLabel}>
      {items.map((item, index) => {
        const share = item.share === null ? null : item.share ?? (total > 0 ? (item.value / total) * 100 : 0);
        return (
          <div key={`${item.label}-${index}`}>
            <span title={item.label}>{item.label}</span>
            <i>
              <b style={{ width: `${Math.max(2, (item.value / max) * 100)}%` }} />
            </i>
            <strong>{item.display ?? item.value.toLocaleString("zh-CN")}</strong>
            <small>
              {share === null ? "" : `${share.toFixed(1)}%`}
              {item.hint ? ` · ${item.hint}` : ""}
            </small>
          </div>
        );
      })}
      {note ? <p className="distribution-note">{note}</p> : null}
      {compareLabel ? <p className="distribution-note">{compareLabel}</p> : null}
    </div>
  );
}

export interface LayerItem {
  key: string;
  label: string;
  value: number;
  comparison?: string;
}

/**
 * Mutually exclusive platform layers plus their registered total.
 *
 * `fans.connection_funnel` / `seeding.seeding_link_structure` satisfy
 * `value(1) + value(2) + value(3) + value(4) === value(5)` in every observed snapshot and
 * `value(5)` equals the registered monthly connected-user metric, so they are drawn as a partition
 * with an explicit total instead of a funnel.
 */
export function LayerStack({
  layers,
  total,
  ariaLabel,
  totalLabel,
  note,
}: {
  layers: LayerItem[];
  total: LayerItem;
  ariaLabel: string;
  totalLabel: string;
  note?: string;
}) {
  const summed = layers.reduce((sum, layer) => sum + Math.max(0, layer.value), 0);
  const base = total.value > 0 ? total.value : summed || 1;
  const matches = Math.abs(summed - total.value) <= Math.max(1, total.value * 0.000001);
  return (
    <div className="layer-stack" role="img" aria-label={ariaLabel}>
      <div className="layer-bar">
        {layers.map((layer, index) => (
          <i
            key={layer.key}
            className={`layer-segment layer-${index % 5}`}
            style={{ width: `${Math.max(1, (layer.value / base) * 100)}%` }}
            title={`${layer.label} ${layer.value.toLocaleString("zh-CN")}`}
          >
            <span>{(layer.value / base * 100).toFixed(1)}%</span>
          </i>
        ))}
      </div>
      <div className="layer-rows">
        {layers.map((layer, index) => (
          <div key={layer.key}>
            <em className={`layer-dot layer-${index % 5}`} />
            <span>{layer.label}</span>
            <strong>{layer.value.toLocaleString("zh-CN")}</strong>
            <small>{((layer.value / base) * 100).toFixed(2)}%</small>
            {layer.comparison ? <b>{layer.comparison}</b> : null}
          </div>
        ))}
        <div className="layer-total">
          <em className="layer-dot total" />
          <span>{totalLabel}</span>
          <strong>{total.value.toLocaleString("zh-CN")}</strong>
          <small>100.00%</small>
          {total.comparison ? <b>{total.comparison}</b> : null}
        </div>
      </div>
      <p className="layer-verify">
        各层合计 {summed.toLocaleString("zh-CN")}
        {matches ? "，与合计值一致" : "，与合计值不一致（平台返回关系异常，请按原值核对）"}
      </p>
      {note ? <p className="distribution-note">{note}</p> : null}
    </div>
  );
}

export interface CompareRow {
  label: string;
  rate: string;
  versusMarket: string;
  versusPeer: string;
}

/** Three-column comparison: this creator / platform market average / peer percentile. */
export function CompareRows({ rows, note }: { rows: CompareRow[]; note?: string }) {
  if (!rows.length) return <EmptyNote>该对比没有可展示的维度。</EmptyNote>;
  return (
    <div className="compare-table">
      <div className="compare-head">
        <span>维度</span>
        <span>本达人</span>
        <span>对比大盘</span>
        <span>对比同行</span>
      </div>
      {rows.map((row) => (
        <div key={row.label}>
          <strong>{row.label}</strong>
          <span>{row.rate}</span>
          <span>{row.versusMarket}</span>
          <span>{row.versusPeer}</span>
        </div>
      ))}
      {note ? <p className="distribution-note">{note}</p> : null}
    </div>
  );
}

/** A fixed-width range pill for a platform interval value such as `20,000 - 100,000`. */
export function RangePill({ label, value, note }: { label: string; value: string; note?: string }) {
  const empty = value === "—";
  return (
    <div className={`range-pill${empty ? " empty" : ""}`}>
      <span>{label}</span>
      <b>{value}</b>
      {note ? <small>{note}</small> : null}
    </div>
  );
}
