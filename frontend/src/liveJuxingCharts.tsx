import type { IndexDimension, TrendPoint } from "./liveJuxingModel";

const WIDTH = 340;

function pointsFor(
  values: Array<{ key: string; value: number }>,
  radius: number,
  center = 160,
): Array<{ x: number; y: number }> {
  const count = Math.max(1, values.length);
  return values.map((item, index) => {
    const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
    const ratio = Math.max(0, Math.min(100, item.value)) / 100;
    return {
      x: center + Math.cos(angle) * radius * ratio,
      y: center + Math.sin(angle) * radius * ratio,
    };
  });
}

function polygon(points: Array<{ x: number; y: number }>): string {
  return points.map((point) => `${point.x},${point.y}`).join(" ");
}

export function RadarChart({
  current,
  sameFansAvg,
}: {
  current: IndexDimension[];
  sameFansAvg: IndexDimension[];
}) {
  if (!current.length) {
    return <p className="live-empty">暂无雷达数据</p>;
  }
  const size = 300;
  const center = size / 2;
  const radius = 102;
  const averageByKey = new Map(sameFansAvg.map((item) => [item.key, item]));
  const axisCount = current.length;
  const currentPoints = pointsFor(current, radius, center);
  const averagePoints = current
    .map((item, index) => {
      const average = averageByKey.get(item.key);
      if (!average) return null;
      const angle = (Math.PI * 2 * index) / axisCount - Math.PI / 2;
      const ratio = Math.max(0, Math.min(100, average.value)) / 100;
      return {
        x: center + Math.cos(angle) * radius * ratio,
        y: center + Math.sin(angle) * radius * ratio,
      };
    })
    .filter((point): point is { x: number; y: number } => Boolean(point));
  const labels = current.map((item, index) => {
    const angle = (Math.PI * 2 * index) / axisCount - Math.PI / 2;
    return {
      text: item.label,
      x: center + Math.cos(angle) * (radius + 24),
      y: center + Math.sin(angle) * (radius + 24),
    };
  });
  return (
    <svg
      className="live-radar"
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label="达人指数雷达图"
    >
      {[25, 50, 75, 100].map((level) => (
        <polygon
          key={level}
          points={polygon(
            Array.from({ length: axisCount }, (_, index) => {
              const angle = (Math.PI * 2 * index) / axisCount - Math.PI / 2;
              return {
                x: center + Math.cos(angle) * radius * (level / 100),
                y: center + Math.sin(angle) * radius * (level / 100),
              };
            }),
          )}
          fill="none"
          stroke="#e5e2dc"
          strokeWidth={level === 100 ? 1.2 : 1}
        />
      ))}
      {current.map((item, index) => {
        const angle = (Math.PI * 2 * index) / axisCount - Math.PI / 2;
        return (
          <line
            key={item.key}
            x1={center}
            y1={center}
            x2={center + Math.cos(angle) * radius}
            y2={center + Math.sin(angle) * radius}
            stroke="#e6e2dc"
          />
        );
      })}
      <polygon
        points={polygon(currentPoints)}
        fill="rgba(66,99,209,.16)"
        stroke="#4263d1"
        strokeWidth="1.8"
      />
      {averagePoints.length > 0 && (
        <polyline
          points={polygon(averagePoints)}
          fill="none"
          stroke="#ed6546"
          strokeWidth="1.5"
          strokeDasharray="5 4"
        />
      )}
      {current.map((item, index) => (
        <circle
          key={item.key}
          cx={currentPoints[index]?.x}
          cy={currentPoints[index]?.y}
          r="3.2"
          fill="#4263d1"
        >
          <title>{`${item.label}: ${item.value.toFixed(2)}`}</title>
        </circle>
      ))}
      {labels.map((label) => (
        <text
          key={label.text}
          x={label.x}
          y={label.y}
          textAnchor="middle"
          dominantBaseline="middle"
          className="live-radar-label"
        >
          {label.text}
        </text>
      ))}
    </svg>
  );
}

export function TrendChart({
  points,
  label,
  color = "#4263d1",
  height = 180,
}: {
  points: TrendPoint[];
  label?: string;
  color?: string;
  height?: number;
}) {
  if (!points.length) return <p className="live-empty">暂无趋势数据</p>;
  const padding = { left: 38, right: 12, top: 16, bottom: 24 };
  const width = WIDTH;
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.max(1, Math.abs(max));
  const x = (index: number) =>
    padding.left + (points.length === 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = (value: number) =>
    padding.top + innerHeight - ((value - min) / span) * innerHeight;
  const line = points.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const area = `${padding.left},${padding.top + innerHeight} ${line} ${padding.left + innerWidth},${padding.top + innerHeight}`;
  const first = points[0];
  const last = points[points.length - 1];
  return (
    <svg
      className="live-trend"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label ?? "趋势图"}
    >
      <line
        x1={padding.left}
        y1={padding.top + innerHeight}
        x2={padding.left + innerWidth}
        y2={padding.top + innerHeight}
        stroke="#e5e2dc"
      />
      <text x={4} y={padding.top + 6} className="live-axis-label">
        {max.toLocaleString("zh-CN")}
      </text>
      <text x={4} y={padding.top + innerHeight} className="live-axis-label">
        {min.toLocaleString("zh-CN")}
      </text>
      <polygon points={area} fill={`${color}14`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="1.8" />
      {points.map((point, index) => (
        <circle key={`${point.label}-${index}`} cx={x(index)} cy={y(point.value)} r="2.2" fill={color}>
          <title>{`${point.label}: ${point.value.toLocaleString("zh-CN")}`}</title>
        </circle>
      ))}
      <text x={padding.left} y={height - 5} className="live-axis-label">
        {first.label}
      </text>
      <text x={padding.left + innerWidth} y={height - 5} textAnchor="end" className="live-axis-label">
        {last.label}
      </text>
    </svg>
  );
}

export function BarChart({
  items,
  height = 170,
  color = "#4263d1",
  valueLabel = "",
}: {
  items: Array<{ label: string; value: number }>;
  height?: number;
  color?: string;
  valueLabel?: string;
}) {
  if (!items.length) return <p className="live-empty">暂无图表数据</p>;
  const width = WIDTH;
  const padding = { left: 8, right: 8, top: 20, bottom: 30 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const max = Math.max(...items.map((item) => item.value), 1);
  const slot = innerWidth / items.length;
  const barWidth = Math.min(26, slot * 0.55);
  return (
    <svg
      className="live-bars"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={valueLabel || "柱状图"}
    >
      {items.map((item, index) => {
        const barHeight = Math.max(2, (item.value / max) * innerHeight);
        const x = padding.left + slot * index + (slot - barWidth) / 2;
        const y = padding.top + innerHeight - barHeight;
        return (
          <g key={`${item.label}-${index}`}>
            <rect x={x} y={y} width={barWidth} height={barHeight} rx="3" fill={color} />
            <text x={x + barWidth / 2} y={y - 5} textAnchor="middle" className="live-axis-label">
              {item.value.toLocaleString("zh-CN")}
            </text>
            <text
              x={padding.left + slot * index + slot / 2}
              y={height - 9}
              textAnchor="middle"
              className="live-axis-label"
            >
              {item.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function DistributionList({
  points,
  emptyText = "暂无数据",
}: {
  points: Array<{ label: string; value: number; tgi: number | null }>;
  emptyText?: string;
}) {
  if (!points.length) return <p className="live-empty">{emptyText}</p>;
  return (
    <div className="distribution-list live-distribution">
      {points.map((point) => (
        <div key={`${point.label}-${point.value}`}>
          <span>{point.label}</span>
          <i>
            <b style={{ width: `${Math.max(1, Math.min(100, point.value * 100))}%` }} />
          </i>
          <strong>
            {(point.value * 100).toFixed(1)}%
            {point.tgi !== null && <small>TGI {point.tgi}</small>}
          </strong>
        </div>
      ))}
    </div>
  );
}
