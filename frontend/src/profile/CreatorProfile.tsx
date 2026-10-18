/**
 * Creator detail workspace: a sticky identity rail plus chapter tabs.
 *
 * Layout follows the 巨量星图 creator homepage (a left profile card with the identity block, the four
 * metrics and the platform's own field order — 达人类型 / 内容主题 / 行业标签 — and 介绍) with one extra
 * chapter for the cooperation history the library entry owns.
 *
 * CD-03 需求调整（见 docs/tasks/CD-03.md）：星图ID 移到昵称下方；四项指标改为
 * 月连接用户数 → 月深度用户 → 粉丝 → 月涨粉率；数量指标按 万/k 展示；去掉「采集完整」、
 * 「观测时间」、「完整性」、指定说明文案与「数据来源」入口。数据本身与快照选择规则未改动。
 *
 * CD-05 需求调整（见 docs/tasks/CD-05.md）：移除「达人概览」章节，默认进入「商业能力」，
 * 只保留 商业能力 / 创作能力 / 履约能力 / 连接用户（达人库入口另有 报价与历史）。
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, Check, Copy, MapPin } from "lucide-react";
import { Link } from "react-router-dom";
import { countUnitText, numberOrNull, ratioPercentText } from "../format";
import { useFieldCatalog, indexCatalog } from "../fieldCatalog";
import type { CreatorLibraryDetail, CreatorVideoPage, LibraryMetric } from "../types";
import { AudiencePanel } from "./audience";
import { CommercialPanel, type FeaturedContent } from "./commercial";
import { CreationPanel, FulfillmentPanel } from "./panels";
import { genderDisplay } from "./views";

export interface CreatorProfileProps {
  creator: CreatorLibraryDetail;
  payload: Record<string, unknown>;
  backTo: string;
  backLabel: string;
  scopeLabel: string;
  /**
   * 采集完整/数据不完整 标识。CD-03 需求 4.1 起，左栏不再渲染该文案；参数保留以免破坏两个入口的
   * 调用契约，`profile_complete`/`pipeline_complete` 本身及其判定逻辑未被改动。
   */
  badgeLabel?: string;
  badgeTone?: string;
  /** 左栏底部说明（任务入口的快照语义提示）；为空时不渲染。 */
  description?: string;
  notice?: ReactNode;
  /**
   * 两组精选视频集合（CD-04 起由「商业能力」章节内的 优秀传播视频 / 优秀种草视频 渲染）。
   * 每个入口各自提供真实数据源：任务入口读任务快照集合，达人库入口读该达人最新快照集合。
   */
  contents?: FeaturedContent;
  /**
   * 「创作能力 → 最新视频表现」的作品观测（DATA-02）。两个入口的数据范围不同、形状相同：
   * 任务入口读本任务快照的观测，达人库入口读该达人当前快照的观测；为空时该面板按空集降级。
   */
  videos?: CreatorVideoPage | null;
  videosLoading?: boolean;
  videosError?: unknown;
  onRetryVideos?: () => void;
  /** 该入口的授权封面端点构造器（按任务或按达人授权）；缺省时不构造任何封面地址。 */
  videoCoverUrl?: (objectId: string) => string;
  /** 报价与历史; only the library entry owns the cross-task read model. */
  historyChapter?: ReactNode;
  /** 入口动作（达人库的“手动更新”）；任务快照入口不提供。 */
  actions?: ReactNode;
  /**
   * 抽屉等覆层内容。CD-03 需求 4.10 移除了左栏的「数据来源」入口，但字段来源/单位/观测时间数据
   * 仍然属于本页；两个入口通过这里挂载 `ProvenanceDrawer`，不随入口不同而丢失。
   */
  overlay?: ReactNode;
}

/**
 * 达人详情的章节标识。
 *
 * CD-05 需求：移除「达人概览」，最终只保留 商业能力 / 创作能力 / 履约能力 / 连接用户（达人库入口另有
 * 报价与历史）。`overview` 不再是章节，`normaliseLegacySection` 负责把旧标识吞成默认章节。
 */
type ChapterKey = "commercial" | "creation" | "fulfillment" | "audience" | "history";

/** 默认进入「商业能力」（CD-05 需求 3.3）。 */
const DEFAULT_CHAPTER: ChapterKey = "commercial";

/**
 * 旧「达人概览」标识的兼容处理（CD-05 需求 3.3）。
 *
 * 本页的章节状态是组件内状态，没有路由级 Tab 参数，因此不存在"旧 Tab 参数解析"这条路径；真正会带旧标识
 * 进来的是页内锚点（外部链接或书签可能仍是 `#overview`，`overview` 也正是 CD-02/03/04 给概览面板用的
 * `id`）。这里把旧的 overview 锚点改写成默认章节的锚点，使它落到一个真实存在的章节，而不是留下一个
 * 指向不存在元素的空白定位；同时保留其余章节的正常锚点行为。URL 里有无法识别的章节标识时同样不会报错，
 * 只是回落到默认章节。
 */
function normaliseLegacySection(): ChapterKey | null {
  if (typeof window === "undefined") return null;
  const section = decodeURIComponent(window.location.hash.replace(/^#/, "").trim());
  if (!section) return null;
  if (section === "overview" || section === "达人概览") {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${DEFAULT_CHAPTER}`);
    return DEFAULT_CHAPTER;
  }
  return null;
}

/**
 * A rail metric as display text.
 *
 * `value` is the parsed platform amount and is preferred: the count then renders in 万/k through
 * `countUnitText`, which is the unit 巨量星图 itself prints. `raw_value` is the platform's own
 * formatted text (for example `1,158w`) and is only used when no numeric amount is available, so a
 * metric never collapses to a dash just because the projection kept only the platform string.
 */
function metricValue(metric: LibraryMetric, kind: "count" | "ratio" = "count"): string {
  if (kind === "ratio") {
    const raw = metric.value ?? metric.raw_value;
    return raw === null || raw === undefined ? "—" : ratioPercentText(raw);
  }
  const amount = numberOrNull(metric.value);
  if (amount !== null) return countUnitText(amount, { approximate: metric.is_approximate });
  if (metric.raw_value && metric.raw_value.trim()) return metric.raw_value;
  return "—";
}

/**
 * The 星图ID under the nickname.
 *
 * `creator.platform_creator_id` is `basic.platform_creator_id` (`path_ref: id`), whose registered
 * contract name is exactly「星图ID」— confirmed against 巨量星图 by the reference page for
 * C位小师妹 (`7360610271510921225`). The internal `creator_id` UUID is never shown here. The value is
 * rendered as-is (a 19-digit id must not be parsed as a number) and stays copyable.
 */
function StarId({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="rail-star-id"
      type="button"
      title={`复制星图ID ${value}`}
      onClick={() => {
        void navigator.clipboard
          ?.writeText(value)
          .then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1600);
          })
          .catch(() => setCopied(false));
      }}
    >
      <span>星图ID</span>
      <strong>{value}</strong>
      {copied ? <Check size={11} /> : <Copy size={11} />}
    </button>
  );
}

/**
 * 调用方没给封面端点时的兜底：永远不产生地址，作品封面走「封面未生成」占位，绝不拼任何链接。
 */
const noCoverUrl = () => "";

export function CreatorProfile({
  creator,
  payload,
  backTo,
  backLabel,
  scopeLabel,
  description,
  notice,
  contents,
  videos,
  videosLoading,
  videosError,
  onRetryVideos,
  videoCoverUrl,
  historyChapter,
  actions,
  overlay,
}: CreatorProfileProps) {
  const catalog = useFieldCatalog();
  const index = useMemo(() => indexCatalog(catalog), [catalog]);
  const [chapter, setChapter] = useState<ChapterKey>(DEFAULT_CHAPTER);
  const gender = genderDisplay(payload);

  // CD-05 需求 3.3：旧「达人概览」标识不得导致空白页。
  // 首次挂载处理直接打开 `/creators/<id>#overview`（整页加载）的情况；同时监听 hashchange，
  // 处理页内跳转（同一文档内改 hash 不会重新挂载组件）——两种情况都落到默认章节。
  useEffect(() => {
    const apply = () => {
      const legacy = normaliseLegacySection();
      if (legacy) setChapter(legacy);
    };
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);

  const chapters: Array<{ key: ChapterKey; label: string }> = [
    { key: "commercial", label: "商业能力" },
    { key: "creation", label: "创作能力" },
    { key: "fulfillment", label: "履约能力" },
    { key: "audience", label: "连接用户" },
  ];
  if (historyChapter) chapters.push({ key: "history", label: "报价与历史" });

  return (
    <div className="page-wrap creator-library-detail">
      <div className="detail-topline">
        <Link to={backTo} className="back-link">
          <ArrowLeft size={17} />
          {backLabel}
        </Link>
        <span>/</span>
        <span>{creator.display_name || "达人详情"}</span>
        {actions ? <div className="detail-actions">{actions}</div> : null}
      </div>
      {notice}
      <div className="profile-layout">
        <aside className="identity-rail" aria-label="达人资料">
          <div className="rail-identity">
            <div className="detail-creator-avatar">
              {creator.avatar_uri ? <img src={creator.avatar_uri} alt="" /> : null}
            </div>
            <div>
              <span className="rail-scope">{scopeLabel}</span>
              <h1>{creator.display_name || "未提供昵称"}</h1>
              <StarId value={creator.platform_creator_id} />
            </div>
          </div>
          <div className="rail-kpis">
            <div>
              <span>月连接用户</span>
              <strong title={creator.monthly_connected_users.raw_value ?? undefined}>
                {metricValue(creator.monthly_connected_users)}
              </strong>
            </div>
            <div>
              <span>月深度用户</span>
              <strong title={creator.monthly_deep_users.raw_value ?? undefined}>
                {metricValue(creator.monthly_deep_users)}
              </strong>
            </div>
            <div>
              <span>粉丝</span>
              <strong title={creator.followers.raw_value ?? undefined}>{metricValue(creator.followers)}</strong>
            </div>
            <div>
              <span>月涨粉率</span>
              <strong>{metricValue(creator.monthly_follower_growth_rate, "ratio")}</strong>
            </div>
          </div>
          <dl className="rail-tags">
            <Fact label="达人类型" items={creator.creator_type_label ? [creator.creator_type_label] : []} />
            <Fact label="内容主题" items={creator.content_theme_labels} />
            <Fact label="行业标签" items={creator.industry_labels} />
          </dl>
          <dl className="rail-facts">
            <div>
              <dt>性别</dt>
              <dd>
                {gender ? (
                  <span className="rail-gender" title={gender.note}>
                    {gender.text}
                  </span>
                ) : (
                  <span className="chip-empty">平台暂无数据</span>
                )}
              </dd>
            </div>
            <div>
              <dt>地区</dt>
              <dd>
                <MapPin size={11} />
                {[creator.province, creator.city].filter(Boolean).join(" · ") || "平台暂无数据"}
              </dd>
            </div>
            <div>
              <dt>MCN</dt>
              <dd>{creator.mcn_name || "平台暂无数据"}</dd>
            </div>
            <div>
              <dt>介绍</dt>
              <dd className="rail-introduction">
                {creator.introduction?.trim() ? (
                  <span>{creator.introduction}</span>
                ) : (
                  <span className="chip-empty">平台暂无数据</span>
                )}
              </dd>
            </div>
          </dl>
          {description ? <p className="rail-description">{description}</p> : null}
        </aside>
        <div className="chapter-area">
          <nav className="chapter-tabs" aria-label="达人详情分区">
            {chapters.map((item) => (
              <button
                key={item.key}
                className={chapter === item.key ? "active" : ""}
                aria-selected={chapter === item.key}
                role="tab"
                onClick={() => setChapter(item.key)}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <div className="chapter-body" role="tabpanel">
            {chapter === "commercial" ? (
              <CommercialPanel payload={payload} index={index} contents={contents} />
            ) : null}
            {chapter === "creation" ? (
              <CreationPanel
                payload={payload}
                index={index}
                videos={videos}
                videosLoading={videosLoading}
                videosError={videosError}
                onRetryVideos={onRetryVideos}
                coverUrl={videoCoverUrl ?? noCoverUrl}
              />
            ) : null}
            {chapter === "fulfillment" ? <FulfillmentPanel payload={payload} index={index} /> : null}
            {chapter === "audience" ? <AudiencePanel payload={payload} index={index} /> : null}
            {chapter === "history" ? historyChapter : null}
          </div>
        </div>
      </div>
      {overlay}
    </div>
  );
}

function Fact({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {items.length ? (
          items.map((item, position) => <em key={`${item}-${position}`}>{item}</em>)
        ) : (
          <span className="chip-empty">平台暂无数据</span>
        )}
      </dd>
    </div>
  );
}
