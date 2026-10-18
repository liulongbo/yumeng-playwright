/**
 * 「创作能力 → 最新视频表现」的柱状图与下方作品列表（CD-05 / DATA-02）。
 *
 * 数据来源：独立存储的作品观测（`GET /api/creator-library/{id}/videos` 或
 * `GET /api/tasks/{task_id}/creators/{id}/videos`），不再从快照 JSONB 的
 * `recent_video_performance` / `recent_xingtu_video_performance` 里取。这里只做**读取与展示**：
 *
 * - 每条柱子严格对应一条视频观测记录；柱高由真实 `play_count` 决定。
 * - 默认展示该视频真实播放量，按 CD-03 已确认的「万/k」规则只做展示层换算，不改原始数据。
 * - X 轴与列表的日期取平台真实 `published_at`（缺失时回落到 `published_raw`），
 *   不使用采集时间或库内更新时间。
 * - 跳转只使用平台真实 `work_url`（仅接受 http(s)）；缺失时不提供可点击入口，不拼接未经验证的地址。
 *
 * 封面说明：`cover_source_uri` 是平台对象存储的**不透明 key**，不是可渲染地址，也绝不构造 CDN 链接。
 * 封面只认观测行给出的 `cover_status` 与已入库对象 id：
 *
 * - `NOT_PROVIDED`：平台响应里没有封面字段 → 「平台未返回封面」。
 * - `UNRESOLVED`：平台给了 key，但还没有已验证的对象 → 「封面未生成」。
 * - `STORED`：`cover_object_id` 非空，交由调用方传入的**授权端点**构造 `src`。
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
import type { CreatorVideoObservation } from "../types";

/** 封面三态；与观测行的 `cover_status` 一一对应，页面不得把三者混为一谈。 */
export type VideoCoverStatus = "STORED" | "UNRESOLVED" | "NOT_PROVIDED";

export interface VideoItem {
  /** 平台唯一作品标识（`platform_item_id` 优先）；用于 React key 与列表/图表一致性核对。 */
  id: string;
  title: string;
  /** 封面状态与已入库对象 id；`src` 由调用方的授权地址构造器决定。 */
  cover: {
    objectId: string | null;
    status: "STORED" | "UNRESOLVED" | "NOT_PROVIDED";
  };
  /** 原始播放量（未换算）。 */
  play: number | null;
  /** 展示用发布时间（`published_at` 优先）。 */
  date: string;
  /** 平台真实作品链接；缺失或非 http(s) 时为 null，不构造。 */
  url: string | null;
}

function text(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

/** Only a platform-provided Douyin work link is clickable; nothing is concatenated here. */
function workUrl(value: unknown): string | null {
  const raw = text(value);
  if (!raw || !/^https?:\/\//i.test(raw)) return null;
  return raw;
}

/** 观测行的 `cover_status` 只认三个已核验取值；异常形状一律按「平台未提供」降级。 */
function coverStatus(value: unknown): VideoCoverStatus {
  if (value === "STORED" || value === "UNRESOLVED" || value === "NOT_PROVIDED") return value;
  return "NOT_PROVIDED";
}

/**
 * Normalise the stored work observations into one shape shared by the chart and the list (CRE-19).
 *
 * 计数可能是 JSON 数字也可能是数字字符串，统一交给 `numberOrNull`；日期优先平台时间戳
 * `published_at`，缺失时用平台原样日期文本 `published_raw`，两者都没有才是「—」。
 */
export function buildVideoItems(rows: CreatorVideoObservation[] | null | undefined): VideoItem[] {
  if (!Array.isArray(rows)) return [];
  return rows.map((row, position) => ({
    id: text(row.platform_item_id) ?? text(row.content_id) ?? `position-${position}`,
    title: text(row.title) ?? "平台未返回标题",
    cover: {
      objectId: text(row.cover_object_id),
      status: coverStatus(row.cover_status),
    },
    play: numberOrNull(row.play_count),
    date: plainDateText(row.published_at ?? row.published_raw),
    url: workUrl(row.work_url),
  }));
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

/**
 * 一条作品封面的三种状态（CRE-14 / DATA-02）。
 *
 * `src` 只由调用方传入的**授权端点**构造器生成（按任务或按达人授权），因此这里不拼任何 CDN 地址，
 * 也绝不借用其它作品的封面。加载失败时保持既有降级：显示「封面加载失败」。
 */
function coverFallback(
  status: VideoCoverStatus,
  objectId: string | null,
  failed: boolean,
): { text: string; title: string } {
  if (failed) {
    return {
      text: "封面加载失败",
      title: "封面对象已登记，但本次未能加载；刷新或重新采集该达人后可再试。",
    };
  }
  if (status === "NOT_PROVIDED") {
    return {
      text: "平台未返回封面",
      title: "平台本次响应里没有该作品的封面字段，因此不展示封面，也不会构造任何地址。",
    };
  }
  if (status === "UNRESOLVED" || !objectId) {
    return {
      text: "封面未生成",
      title: "平台返回了封面 key，但还没有存成可访问的封面对象；生成后会显示。",
    };
  }
  return {
    text: "封面未生成",
    title: "该作品登记了封面对象，但当前入口没有可用的封面地址；不构造任何链接。",
  };
}

function VideoCover({
  objectId,
  status,
  coverUrl,
  alt,
  className,
  fallbackClassName,
}: {
  objectId: string | null;
  status: VideoCoverStatus;
  coverUrl: (objectId: string) => string;
  alt: string;
  className: string;
  fallbackClassName: string;
}) {
  const [failed, setFailed] = useState(false);
  // 换一条作品（对象 id 变化）时重置失败态，避免上一张封面的失败态泄漏到下一张。
  useEffect(() => setFailed(false), [objectId, status]);
  const src = status === "STORED" && objectId ? coverUrl(objectId) : null;
  if (!src || failed) {
    const fallback = coverFallback(status, objectId, failed);
    return (
      <div className={`${className} ${fallbackClassName}`}>
        <ImageOff size={16} />
        <span title={fallback.title}>{fallback.text}</span>
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

export function VideoPerformance({
  items,
  coverUrl,
}: {
  items: VideoItem[];
  coverUrl: (objectId: string) => string;
}) {
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
            objectId={tooltip.item.cover.objectId}
            status={tooltip.item.cover.status}
            coverUrl={coverUrl}
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
                objectId={item.cover.objectId}
                status={item.cover.status}
                coverUrl={coverUrl}
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
