/**
 * 「创作能力 → 最新视频表现」的柱状图与下方作品列表（CD-05）。
 *
 * 数据来源：`payload.modules.creation.fields[]` 中 `field_key` 为
 * `recent_video_performance` / `recent_xingtu_video_performance` 的 `FieldObservation`，其
 * `value.data` 是**视频对象数组**（实测 15 条/达人）。这里只做**读取与展示**：
 *
 * - 每条柱子严格对应一条视频记录，`item_id` 为唯一标识；柱高由真实 `play` 决定。
 * - 默认展示该视频真实播放量，按 CD-03 已确认的「万/k」规则只做展示层换算，不改原始数据。
 * - X 轴与列表的日期取平台真实 `item_date`（无该字段时回落到 Unix 秒 `create_time`），
 *   不使用采集时间或库内更新时间。
 * - 跳转只使用平台真实 `url`；缺失时不提供可点击入口，不拼接未经验证的地址。
 *
 * 封面说明：JSONB 中的 `item_cover` / `head_image_uri` 是平台对象存储的**不透明 key**，不是可直接
 * 渲染的地址（真实开发库 1845 条非空封面中 0 条是完整 URL，且从未入库对象存储）。因此封面的
 * `src` 只接受真正的 http(s) 地址；否则走与精选作品一致的「暂无封面」降级，绝不构造未经验证的 CDN 链接。
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { ExternalLink, ImageOff } from "lucide-react";
import { countText, countUnitText, numberOrNull, plainDateText } from "../format";

export interface VideoItem {
  /** 平台唯一作品标识；用于 React key 与列表/图表一致性核对。 */
  id: string;
  title: string;
  /** 仅当平台给出真正的 http(s) 封面地址时才有值。 */
  coverUrl: string | null;
  /** 原始播放量（未换算）。 */
  play: number | null;
  /** 展示用发布时间（`item_date` 优先）。 */
  date: string;
  /** 平台真实作品链接；缺失时为 null，不构造。 */
  url: string | null;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

/**
 * A cover is only usable when the platform handed over a real http(s) URL.
 *
 * The video records carry `tos-cn-i-…/<key>` object-store keys, which are **not** renderable and must
 * not be turned into a guessed CDN URL; those degrade to the existing empty-cover state.
 */
function coverUrl(value: unknown): string | null {
  const raw = text(value);
  if (!raw || !/^https?:\/\//i.test(raw)) return null;
  return raw;
}

/** Only a platform-provided Douyin work link is clickable; nothing is concatenated here. */
function workUrl(value: unknown): string | null {
  const raw = text(value);
  if (!raw || !/^https?:\/\//i.test(raw)) return null;
  return raw;
}

/** The real publish date: platform `item_date`, falling back to the Unix-second `create_time`. */
function publishDate(item: Record<string, unknown>): string {
  const explicit = plainDateText(item.item_date ?? item.item_date_str ?? null);
  if (explicit !== "—") return explicit;
  const stamp = numberOrNull(item.create_time ?? item.create_timestamp);
  if (stamp !== null && stamp > 0) {
    return plainDateText(new Date(stamp * 1000).toISOString());
  }
  return "—";
}

/** Normalise raw platform records into one shape shared by the chart and the list (CRE-19). */
export function buildVideoItems(data: unknown): VideoItem[] {
  if (!Array.isArray(data)) return [];
  return data
    .map((raw, position) => {
      const item = record(raw);
      if (!item) return null;
      const id =
        text(item.item_id) ?? text(item.video_id) ?? text(item.aweme_id) ?? `position-${position}`;
      const title = text(item.title) ?? text(item.item_title) ?? "平台未返回标题";
      return {
        id,
        title,
        coverUrl: coverUrl(item.item_cover ?? item.head_image_uri),
        play: numberOrNull(item.play),
        date: publishDate(item),
        url: workUrl(item.url),
      } satisfies VideoItem;
    })
    .filter((item): item is VideoItem => item !== null);
}

/**
 * The play-count label shown above every bar by default.
 *
 * Bars keep the platform's real play count as their height; the label is display-only. It is always
 * the 万/k form this round asks for (`915,520 → 91.6万`), which also keeps a crowded 15-column row
 * readable — a grouped `2,719,270` would collide with its neighbour and could not fit at all.
 * The raw head-count is never overwritten; the list and the tooltip still show the exact figure.
 */
function playLabel(value: number | null): string {
  return countUnitText(value);
}

/** A cover with the same degrade behaviour as the featured cards (CRE-14). */
function VideoCover({
  src,
  alt,
  className,
  fallbackClassName,
}: {
  src: string | null;
  alt: string;
  className: string;
  fallbackClassName: string;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  if (!src || failed) {
    return (
      <div className={`${className} ${fallbackClassName}`}>
        <ImageOff size={16} />
        <span>{src ? "封面加载失败" : "平台未提供封面地址"}</span>
      </div>
    );
  }
  return (
    <div className={className}>
      <img src={src} alt={alt} decoding="async" onError={() => setFailed(true)} />
    </div>
  );
}

const TOOLTIP_WIDTH = 236;
const TOOLTIP_ESTIMATED_HEIGHT = 214;
const TOOLTIP_GAP = 10;

interface TooltipState {
  item: VideoItem;
  position: number;
  left: number;
  top: number;
}

export function VideoPerformance({ items }: { items: VideoItem[] }) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const closeTimer = useRef<number | null>(null);

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  const openTooltip = useCallback(
    (item: VideoItem, position: number, element: HTMLElement) => {
      cancelClose();
      const box = element.getBoundingClientRect();
      // Fixed positioning keeps the layer out of `.video-bars`' horizontal scroll box, so a tall bar
      // can never have its tooltip clipped by an `overflow` ancestor (CRE-12).
      const half = TOOLTIP_WIDTH / 2;
      const left = Math.min(
        Math.max(box.left + box.width / 2, half + 8),
        window.innerWidth - half - 8,
      );
      const above = box.top - TOOLTIP_ESTIMATED_HEIGHT - TOOLTIP_GAP;
      const top = above >= 8 ? above : Math.min(box.bottom + TOOLTIP_GAP, window.innerHeight - 120);
      setTooltip({ item, position, left, top });
    },
    [cancelClose],
  );

  /** Leaving the bar starts a short close, so moving onto the tooltip does not dismiss it (CRE-12). */
  const scheduleClose = useCallback(() => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => setTooltip(null), 160);
  }, [cancelClose]);

  useEffect(() => cancelClose, [cancelClose]);

  const max = useMemo(
    () => Math.max(...items.map((item) => item.play ?? 0), 1),
    [items],
  );

  if (!items.length) {
    return <p className="muted video-empty">本次没有视频记录。</p>;
  }

  return (
    <>
      <div
        className={`video-bars${
          tooltip && tooltip.position >= 0 ? " has-active" : ""
        }`}
        aria-label="视频播放量柱状图"
      >
        {items.map((item, position) => {
          const height = Math.max(3, ((item.play ?? 0) / max) * 100);
          const active = tooltip?.position === position;
          const label = playLabel(item.play);
          const barBody = (
            <>
              <b className="video-bar-value">{label}</b>
              <i style={{ height: `${height}%` }} />
            </>
          );
          const shared = {
            className: `video-bar${active ? " active" : ""}`,
            "data-video-id": item.id,
            onMouseEnter: (event: MouseEvent<HTMLElement>) =>
              openTooltip(item, position, event.currentTarget),
            onMouseLeave: scheduleClose,
            onFocus: (event: FocusEvent<HTMLElement>) =>
              openTooltip(item, position, event.currentTarget),
            onBlur: scheduleClose,
          };
          return (
            <div
              key={`${item.id}-${position}`}
              className="video-bar-slot"
              data-active={active ? "true" : undefined}
            >
              {item.url ? (
                <a
                  {...shared}
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`在抖音打开作品：${item.title}`}
                >
                  {barBody}
                </a>
              ) : (
                <div {...shared}>{barBody}</div>
              )}
              <span className="video-bar-date" title={item.date}>
                {item.date}
              </span>
            </div>
          );
        })}
      </div>
      {tooltip ? (
        <div
          className="video-tip"
          role="tooltip"
          style={{ left: tooltip.left, top: tooltip.top }}
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
        >
          <VideoCover
            src={tooltip.item.coverUrl}
            alt=""
            className="video-tip-cover"
            fallbackClassName="video-tip-cover-empty"
          />
          <strong title={tooltip.item.title}>{tooltip.item.title}</strong>
          <div className="video-tip-meta">
            <span>
              播放量 <b>{countText(tooltip.item.play)}</b>
            </span>
            <span>{tooltip.item.date}</span>
          </div>
          {tooltip.item.url ? (
            <a
              className="video-tip-link"
              href={tooltip.item.url}
              target="_blank"
              rel="noreferrer"
            >
              在抖音打开作品
              <ExternalLink size={11} />
            </a>
          ) : (
            <em className="video-tip-nolink">平台未返回作品链接</em>
          )}
        </div>
      ) : null}
      <div className="video-list">
        {items.map((item) => {
          const body: ReactNode = (
            <>
              <VideoCover
                src={item.coverUrl}
                alt=""
                className="video-card-cover"
                fallbackClassName="video-card-cover-empty"
              />
              <div className="video-card-copy">
                <strong title={item.title}>{item.title}</strong>
                <div className="video-card-meta">
                  <span>播放量 <b>{countText(item.play)}</b></span>
                  <span>{item.date}</span>
                </div>
              </div>
            </>
          );
          return item.url ? (
            <a
              key={`${item.id}-card`}
              className="video-card"
              href={item.url}
              target="_blank"
              rel="noreferrer"
              aria-label={`在抖音打开作品：${item.title}`}
            >
              {body}
            </a>
          ) : (
            <div key={`${item.id}-card`} className="video-card no-link">
              {body}
            </div>
          );
        })}
      </div>
    </>
  );
}
