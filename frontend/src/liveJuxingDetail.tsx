import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { LiveMetricEnvelope } from "./types";
import {
  type CommercePeriod,
  type JuxingLiveModel,
  type PortraitSide,
  type Resolved,
  type WorkItem,
  buildJuxingLiveModel,
  formatCount,
  formatDate,
  formatDuration,
  formatIndexScore,
  formatMoney,
  formatPercent,
  formatRange,
  formatScore,
  formatUnitCount,
  hotBrandList,
  hotCategoryList,
  isCollected,
  statusText,
  textList,
} from "./liveJuxingModel";
import { BarChart, DistributionList, RadarChart, TrendChart } from "./liveJuxingCharts";

const METRIC_OPTIONS = [
  ["viewCount", "观看量"],
  ["peakOnlineCount", "最高在线人数"],
  ["commentCount", "评论数"],
  ["shareCount", "分享数"],
] as const;

const FREQUENCY_MODES = [
  ["month", "按月"],
  ["week", "按周"],
  ["hour", "按时"],
] as const;

const PORTRAIT_LABELS: Record<string, string> = {
  gender: "性别分布",
  age: "年龄分布",
  device_brand: "设备分布",
  device_price: "设备价格分布",
  device_type: "设备类型分布",
  activity: "活跃度",
  city_tier: "城市等级分布",
  city: "城市分布",
  province: "地域分布",
  region: "省份及城市分布",
  interest: "兴趣分布",
  nine_major_groups: "九大人群",
};

function Metric({
  label,
  field,
  format = (value) => String(value ?? "暂无数据"),
  hint,
}: {
  label: string;
  field: Resolved;
  format?: (value: unknown) => string;
  hint?: string;
}) {
  const collected = isCollected(field.field);
  return (
    <div className="live-kpi">
      <span>{label}</span>
      <strong>{collected ? format(field.value) : statusText(field.field)}</strong>
      <small>
        {field.fallback ? "上次成功值" : field.field?.period_label ?? hint ?? "平台原生口径"}
      </small>
    </div>
  );
}

function Tags({ label, field }: { label: string; field: Resolved }) {
  const values =
    typeof field.value === "string"
      ? field.value.trim()
        ? [field.value.trim()]
        : []
      : textList(field.value);
  return (
    <div className="live-tag-line">
      <span>{label}</span>
      <div className="live-tags">
        {values.length ? values.map((value) => <b key={value}>{value}</b>) : <em>{statusText(field.field)}</em>}
      </div>
    </div>
  );
}

function Section({
  title,
  description,
  children,
  extra,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  extra?: ReactNode;
}) {
  return (
    <section className="profile-panel live-section">
      <div className="profile-heading">
        <div>
          <h3>{title}</h3>
          {description && <p>{description}</p>}
        </div>
        {extra}
      </div>
      {children}
    </section>
  );
}

function quoteFallback(data: JuxingLiveModel) {
  return data.quotes;
}

function WorkCard({ work, observedAt }: { work: WorkItem; observedAt?: string | null }) {
  return (
    <article className="live-work-card">
      <div className="live-work-cover">
        {work.coverUrl ? (
          <img src={work.coverUrl} alt="" loading="lazy" />
        ) : (
          <span>暂无封面</span>
        )}
        <small>{work.hasSkuInfo ? "电商带货" : "直播作品"}</small>
      </div>
      <div className="live-work-copy">
        <strong title={work.title ?? ""}>{work.title || "未提供作品名称"}</strong>
        <div className="live-work-meta">
          <span>{formatUnitCount(work.viewCount)} 观看</span>
          <span>{formatDuration(work.durationSeconds)}</span>
          <span>{formatDate(work.publishedAt ?? observedAt)}</span>
        </div>
        <div className="live-work-meta">
          <span>最高在线 {formatCount(work.peakOnlineCount)}</span>
          <span>评论 {formatCount(work.commentCount)}</span>
          <span>分享 {formatCount(work.shareCount)}</span>
        </div>
        {work.mediaUrl ? (
          <a href={work.mediaUrl} target="_blank" rel="noreferrer" className="live-work-link">
            平台播放地址（有时效）
          </a>
        ) : (
          <span className="live-empty-inline">平台未提供可用播放链接</span>
        )}
      </div>
    </article>
  );
}

function PortraitBlock({
  side,
  sideLabel,
  viewerDeviceTags,
}: {
  side: PortraitSide;
  sideLabel: string;
  viewerDeviceTags: string[];
}) {
  const [regionMode, setRegionMode] = useState<"province" | "city">("province");
  const [regionMetric, setRegionMetric] = useState<"share" | "penetration">("share");
  const regionPoints =
    regionMode === "city"
      ? side.dimensions.city ?? []
      : side.dimensions[regionMetric === "share" ? "province_share" : "province_penetration"] ?? [];
  const keys = [
    "gender",
    "age",
    "device_brand",
    "device_price",
    "device_type",
    "activity",
    "city_tier",
    "interest",
    "nine_major_groups",
  ];
  return (
    <div className="live-portrait-block">
      <div className="live-subhead">
        <strong>{sideLabel}</strong>
        <span>分布数据来自平台 listPortrait；独立保存，不互相替代</span>
      </div>
      <div className="live-portrait-grid">
        {keys.map((key) => {
          const points = side.dimensions[key] ?? [];
          const availability = side.availability[key] ?? "NO_DATA";
          if (key === "interest" && side.side === "viewer" && !points.length) {
            return (
              <div className="live-portrait-cell" key={key}>
                <h4>{PORTRAIT_LABELS[key]}</h4>
                <p className="live-empty">平台未提供观众兴趣分布</p>
              </div>
            );
          }
          return (
            <div className="live-portrait-cell" key={key}>
              <h4>{PORTRAIT_LABELS[key] ?? key}</h4>
              {key === "device_type" && availability === "SUMMARY_ONLY" ? (
                <p className="live-hint">
                  仅平台文字摘要：{viewerDeviceTags.join("；") || "暂无"}
                </p>
              ) : (
                <DistributionList points={points} />
              )}
            </div>
          );
        })}
        <div className="live-portrait-cell live-region-cell">
          <div className="live-subhead">
            <h4>{PORTRAIT_LABELS.region}</h4>
            <div className="live-inline-tabs">
              <button
                type="button"
                className={regionMode === "province" ? "active" : ""}
                onClick={() => setRegionMode("province")}
              >
                省份
              </button>
              <button
                type="button"
                className={regionMode === "city" ? "active" : ""}
                onClick={() => setRegionMode("city")}
              >
                城市
              </button>
            </div>
          </div>
          {regionMode === "province" && (
            <div className="live-inline-tabs">
              <button
                type="button"
                className={regionMetric === "share" ? "active" : ""}
                onClick={() => setRegionMetric("share")}
              >
                占比
              </button>
              <button
                type="button"
                className={regionMetric === "penetration" ? "active" : ""}
                onClick={() => setRegionMetric("penetration")}
              >
                渗透
              </button>
            </div>
          )}
          <DistributionList points={regionPoints} />
        </div>
      </div>
      <p className="live-source-note">
        平台原始字段 cityPercentage=城市等级、cityLevelPercentage=城市名；本页按业务语义展示。
      </p>
    </div>
  );
}

export function JuxingLiveSections({
  payload,
  liveMetrics,
  observedAt,
}: {
  payload?: Record<string, unknown>;
  liveMetrics?: Record<string, LiveMetricEnvelope>;
  observedAt?: string | null;
}) {
  const data = useMemo(() => buildJuxingLiveModel(payload, liveMetrics), [payload, liveMetrics]);
  const [collection, setCollection] = useState<"personal" | "commercial">("personal");
  const [ecommerceOnly, setEcommerceOnly] = useState(false);
  const [workPage, setWorkPage] = useState(0);
  const [workMetric, setWorkMetric] = useState<(typeof METRIC_OPTIONS)[number][0]>("viewCount");
  const [frequencyMode, setFrequencyMode] = useState("month");
  const [fanPeriod, setFanPeriod] = useState<"30" | "90">("30");
  const [fanMode, setFanMode] = useState<"total" | "increment">("total");
  const [portraitSide, setPortraitSide] = useState<"viewer" | "fan">("viewer");
  const [commercePeriod, setCommercePeriod] = useState<"7" | "30" | "90">("7");
  const [cooperationPeriod, setCooperationPeriod] = useState<"30" | "90">("30");
  const [reviewPage, setReviewPage] = useState(0);
  const [indexDimension, setIndexDimension] = useState("starIndex");

  const selectedWorks =
    collection === "personal" ? data.works.personalItems : data.works.commercialItems;
  const filteredWorks = ecommerceOnly
    ? selectedWorks.filter((work) => work.hasSkuInfo)
    : selectedWorks;
  const pageSize = 4;
  const pageCount = Math.max(1, Math.ceil(filteredWorks.length / pageSize));
  const safePage = Math.min(workPage, pageCount - 1);
  const currentWorks = filteredWorks.slice(safePage * pageSize, safePage * pageSize + pageSize);
  const recentChart = data.works.recentItems.map((work) => ({
    label: work.title?.slice(0, 6) || work.streamId.slice(-4),
    value: (work[workMetric] as number | null) ?? 0,
  }));
  const frequency = data.works.frequencyModes[frequencyMode];
  const fanData = data.fans[fanPeriod];
  const fanSeries = fanMode === "total" ? fanData.totalSeries : fanData.incrementSeries;
  const side = portraitSide === "viewer" ? data.audience.viewerSide : data.audience.fanSide;
  const sideField = portraitSide === "viewer" ? data.audience.viewer : data.audience.fan;
  const commerce = data.commerce.periods[commercePeriod];
  const coop =
    cooperationPeriod === "30" ? data.cooperation.days30 : data.cooperation.days90;
  const reviewsPerPage = 10;
  const reviewPageCount = Math.max(1, Math.ceil(data.cooperation.reviewItems.length / reviewsPerPage));
  const safeReviewPage = Math.min(reviewPage, reviewPageCount - 1);
  const reviewRows = data.cooperation.reviewItems.slice(
    safeReviewPage * reviewsPerPage,
    safeReviewPage * reviewsPerPage + reviewsPerPage,
  );
  const indexSeries =
    data.index.trendSeries.find((series) => series.key === indexDimension) ??
    data.index.trendSeries[0];
  const indexButtons = data.index.selectable.length
    ? data.index.selectable
    : data.index.current.map((item) => item.key);

  return (
    <div className="live-juxing-sections">
      {data.isLegacy && (
        <div className="draft-banner">
          <div>
            <strong>该达人尚未按新版字段采集</strong>
            <span>当前展示的是旧版直播快照；请点击「手动更新直播资料」补齐新增字段，系统不会用空值补造。</span>
          </div>
        </div>
      )}

      <Section
        title="基础信息与直播报价"
        description="身份优先复用达人平台身份；报价保留业务类型、计价单位与金额，不合并为统一报价"
      >
        <div className="live-basic-grid">
          <div className="live-basic-identity">
            {isCollected(data.basic.avatar.field) && typeof data.basic.avatar.value === "string" ? (
              <img className="live-avatar" src={data.basic.avatar.value} alt="" />
            ) : (
              <div className="live-avatar live-avatar-empty">暂无头像</div>
            )}
            <div>
              <h3>{data.basic.nickname.value ? String(data.basic.nickname.value) : "未提供昵称"}</h3>
              <p>
                {data.basic.creatorId.value ? `快手ID ${String(data.basic.creatorId.value)}` : "快手ID 暂无数据"}
                {data.basic.starId.value ? ` · starId ${String(data.basic.starId.value)}` : ""}
              </p>
              <p>
                {[data.basic.location.value, data.basic.city.value]
                  .filter((value) => typeof value === "string" && value)
                  .join(" / ") || "地域暂无数据"}
              </p>
              <p>
                粉丝 {formatUnitCount(data.basic.followers.value)} · 机构{" "}
                {data.basic.mcn.value ? String(data.basic.mcn.value) : statusText(data.basic.mcn.field)}
              </p>
            </div>
          </div>
          <div className="live-basic-tags">
            <Tags label="内容分类" field={data.basic.contentTypes} />
            <Tags label="内容形式" field={data.basic.contentForms} />
            <Tags label="所属行业" field={data.basic.industries} />
            <Tags label="认证信息" field={data.basic.verified} />
          </div>
        </div>
        <div className="live-quotes">
          {quoteFallback(data).length ? (
            quoteFallback(data).map((quote) => (
              <div className="live-quote" key={`${quote.pageLabel}-${quote.priceTypeName ?? ""}`}>
                <span>{quote.pageLabel}</span>
                <strong>{formatMoney(quote.priceYuan)}</strong>
                <small>{quote.priceTypeName || "平台报价"}</small>
              </div>
            ))
          ) : (
            <p className="live-empty">{statusText(data.quotesField.field)}</p>
          )}
        </div>
      </Section>

      <Section
        title="数据概览"
        description="最高在线人数与预期最高在线人数是两个不同指标；信用分为空时不显示为 0"
      >
        <div className="live-kpi-grid">
          <Metric label="粉丝数" field={data.basic.followers} format={formatUnitCount} />
          <Metric label="预期观看人数" field={data.overview.expectViewer} format={formatUnitCount} />
          <Metric label="最高在线人数" field={data.overview.maxOnline} format={formatUnitCount} />
          <Metric
            label="预期CPM"
            field={data.overview.expectCpm}
            format={(value) => {
              const amount = Number(value);
              return Number.isFinite(amount) ? String(amount) : "暂无数据";
            }}
          />
          <Metric label="周均直播场次" field={data.overview.weeklySessions} format={formatCount} />
          <Metric label="近30天信用分" field={data.overview.creditScore} format={formatScore} />
          <Metric label="预期最高在线人数" field={data.overview.expectMaxOnline} format={formatCount} />
        </div>
        <div className="live-overview-extra">
          <Tags label="历史合作行业" field={data.overview.cooperationIndustries} />
          <Tags label="观众特征" field={data.overview.viewerFeatureTags} />
          <Tags label="观众设备" field={data.overview.viewerDeviceTags} />
          <Tags label="观众分布" field={data.overview.viewerAreaTags} />
        </div>
        <div className="live-kpi-grid live-kpi-grid-compact">
          {data.overview.supplements.map((field) => (
            <Metric
              key={field.key}
              label={
                {
                  "live.avg_people": "平均观看人数",
                  "live.avg_like": "场均点赞",
                  "live.week_release": "直播周发布",
                  "live.interaction_rate": "直播互动率（平台原值）",
                }[field.key] ?? field.key
              }
              field={field}
              format={(value) => String(value ?? "暂无数据")}
            />
          ))}
        </div>
      </Section>

      <Section
        title="达人指数"
        description="雷达为真实接口数值；同粉丝段均值没有综合指数维度，虚线不补造综合点"
        extra={<span className="live-score-badge">综合指数 {formatIndexScore(data.index.score.value)}</span>}
      >
        {data.index.current.length ? (
          <>
            <div className="live-index-layout">
              <div className="live-radar-wrap">
                <RadarChart current={data.index.current} sameFansAvg={data.index.sameFansAvg} />
                <p className="live-source-note">实线：当前值；虚线：同粉丝段均值（平台无综合均值）</p>
              </div>
              <div className="live-index-ranks">
                <div>
                  <span>同行业达人排名</span>
                  <strong>{formatCount(data.index.industryRank.value)}</strong>
                  <small>
                    {formatPercent(data.index.industryPercent.value)} 达人
                  </small>
                </div>
                <div>
                  <span>同粉丝段达人排名</span>
                  <strong>{formatCount(data.index.fansRank.value)}</strong>
                  <small>
                    {Number(data.index.fansPercent.value) < 0.5
                      ? "低于50%以上达人"
                      : `超越 ${formatPercent(data.index.fansPercent.value)} 达人`}
                  </small>
                </div>
                <div className="live-index-avg-list">
                  {data.index.sameFansAvg.map((item) => (
                    <span key={item.key}>
                      {item.label}均值 <b>{item.value.toFixed(1)}</b>
                    </span>
                  ))}
                </div>
              </div>
            </div>
            <div className="live-trend-block">
              <div className="live-subhead">
                <strong>同类型达人指数趋势</strong>
                <div className="live-inline-tabs">
                  {indexButtons.map((key) => {
                    const label =
                      data.index.trendSeries.find((series) => series.key === key)?.label ??
                      data.index.current.find((item) => item.key === key)?.label ??
                      key;
                    return (
                      <button
                        type="button"
                        key={key}
                        className={indexDimension === key ? "active" : ""}
                        onClick={() => setIndexDimension(key)}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>
              {indexSeries ? (
                <>
                  <TrendChart points={indexSeries.points} label={indexSeries.label} />
                  {data.index.allZero && (
                    <p className="live-hint">平台返回的月度指数全部为 0，已如实展示，不伪造历史趋势。</p>
                  )}
                </>
              ) : (
                <p className="live-empty">{statusText(data.index.trend.field)}</p>
              )}
            </div>
          </>
        ) : (
          <p className="live-empty">{statusText(data.index.dimensions.field)}</p>
        )}
      </Section>

      <Section
        title="代表作品与直播表现"
        description="个人作品与聚星作品全部保存；只看电商带货在页面端按 hasSkuInfo 过滤"
        extra={
          <span className="live-count-badge">
            {collection === "personal"
              ? formatCount(data.works.personalItems.length)
              : formatCount(data.works.commercialItems.length)}{" "}
            条
          </span>
        }
      >
        <div className="live-work-toolbar">
          <div className="live-inline-tabs">
            <button
              type="button"
              className={collection === "personal" ? "active" : ""}
              onClick={() => {
                setCollection("personal");
                setWorkPage(0);
              }}
            >
              个人作品
            </button>
            <button
              type="button"
              className={collection === "commercial" ? "active" : ""}
              onClick={() => {
                setCollection("commercial");
                setWorkPage(0);
              }}
            >
              聚星作品
            </button>
          </div>
          <label className="live-check">
            <input
              type="checkbox"
              checked={ecommerceOnly}
              onChange={(event) => {
                setEcommerceOnly(event.target.checked);
                setWorkPage(0);
              }}
            />
            只看电商带货
          </label>
          <div className="live-pager">
            <button
              type="button"
              disabled={safePage <= 0}
              onClick={() => setWorkPage(Math.max(0, safePage - 1))}
            >
              上一页
            </button>
            <span>
              {safePage + 1}/{pageCount}
            </span>
            <button
              type="button"
              disabled={safePage >= pageCount - 1}
              onClick={() => setWorkPage(Math.min(pageCount - 1, safePage + 1))}
            >
              下一页
            </button>
          </div>
        </div>
        {currentWorks.length ? (
          <div className="live-work-grid">
            {currentWorks.map((work) => (
              <WorkCard key={`${collection}-${work.streamId}`} work={work} observedAt={observedAt} />
            ))}
          </div>
        ) : (
          <p className="live-empty">
            {statusText(
              collection === "personal" ? data.works.personal.field : data.works.commercial.field,
            )}
            {ecommerceOnly ? "（当前无电商带货作品）" : ""}
          </p>
        )}
        <div className="live-work-charts">
          <div>
            <div className="live-subhead">
              <strong>最近15个直播</strong>
              <div className="live-inline-tabs">
                {METRIC_OPTIONS.map(([key, label]) => (
                  <button
                    type="button"
                    key={key}
                    className={workMetric === key ? "active" : ""}
                    onClick={() => setWorkMetric(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <BarChart items={recentChart} valueLabel="最近15个直播" />
            <p className="live-source-note">
              数据源：recentLiveWorks；悬停/标签显示每个作品的平台原值。
            </p>
          </div>
          <div>
            <div className="live-subhead">
              <strong>直播频次分布</strong>
              <div className="live-inline-tabs">
                {FREQUENCY_MODES.map(([key, label]) => (
                  <button
                    type="button"
                    key={key}
                    className={frequencyMode === key ? "active" : ""}
                    onClick={() => setFrequencyMode(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {frequency ? (
              <BarChart items={frequency.items} valueLabel="直播频次" />
            ) : (
              <p className="live-empty">{statusText(data.works.frequency.field)}</p>
            )}
            <p className="live-source-note">
              数据源：queryVideoPlayCnt type=4，近三个月直播次数；周 0=周日、时=小时。
            </p>
          </div>
        </div>
      </Section>

      <Section
        title="粉丝趋势"
        description="近30/90天分开保存；总量与增量各自保留日期点，不混合周期"
      >
        <div className="live-inline-tabs">
          <button
            type="button"
            className={fanPeriod === "30" ? "active" : ""}
            onClick={() => setFanPeriod("30")}
          >
            近30天
          </button>
          <button
            type="button"
            className={fanPeriod === "90" ? "active" : ""}
            onClick={() => setFanPeriod("90")}
          >
            近90天
          </button>
        </div>
        <div className="live-kpi-grid live-kpi-grid-compact">
          <Metric label={`${fanData.label}涨粉数`} field={fanData.growth} format={formatUnitCount} />
          <Metric label={`${fanData.label}涨粉率`} field={fanData.rate} format={formatPercent} />
        </div>
        <div className="live-inline-tabs">
          <button
            type="button"
            className={fanMode === "total" ? "active" : ""}
            onClick={() => setFanMode("total")}
          >
            总量
          </button>
          <button
            type="button"
            className={fanMode === "increment" ? "active" : ""}
            onClick={() => setFanMode("increment")}
          >
            增量
          </button>
        </div>
        {fanSeries.length ? (
          <TrendChart points={fanSeries} label={`${fanData.label}粉丝${fanMode === "total" ? "总量" : "增量"}`} />
        ) : (
          <p className="live-empty">{statusText(fanData.trend.field)}</p>
        )}
      </Section>

      <Section
        title="受众画像"
        description="观众画像与粉丝画像独立保存；设备类型只有文字摘要时如实标注"
      >
        <div className="live-inline-tabs">
          <button
            type="button"
            className={portraitSide === "viewer" ? "active" : ""}
            onClick={() => setPortraitSide("viewer")}
          >
            观众画像
          </button>
          <button
            type="button"
            className={portraitSide === "fan" ? "active" : ""}
            onClick={() => setPortraitSide("fan")}
          >
            粉丝画像
          </button>
        </div>
        {side ? (
          <PortraitBlock
            side={side}
            sideLabel={portraitSide === "viewer" ? "观众画像" : "粉丝画像"}
            viewerDeviceTags={textList(data.overview.viewerDeviceTags.value)}
          />
        ) : (
          <p className="live-empty">{statusText(sideField.field)}</p>
        )}
      </Section>

      <Section
        title="带货数据"
        description="7/30/90 天独立请求；平台返回全 0 且页面显示“-”时按暂无数据展示"
        extra={<span className="live-count-badge">平台原生口径</span>}
      >
        <div className="live-inline-tabs">
          {(["7", "30", "90"] as const).map((period) => (
            <button
              type="button"
              key={period}
              className={commercePeriod === period ? "active" : ""}
              onClick={() => setCommercePeriod(period)}
            >
              近{period}日
            </button>
          ))}
        </div>
        <CommerceBlock period={commerce} />
        <div className="live-hot-grid">
          <div>
            <h4>热销Top品牌</h4>
            {hotBrandList(data.commerce.hotBrands.value).length ? (
              hotBrandList(data.commerce.hotBrands.value).map((brand) => (
                <p key={`${brand.title}-${brand.rank ?? ""}`}>
                  <b>{brand.rank ?? "-"}</b> {brand.title}
                </p>
              ))
            ) : (
              <p className="live-empty">{statusText(data.commerce.hotBrands.field)}</p>
            )}
          </div>
          <div>
            <h4>优势类目</h4>
            {hotCategoryList(data.commerce.hotCategories.value).length ? (
              hotCategoryList(data.commerce.hotCategories.value).map((category) => (
                <p key={`${category.title}-${category.rank ?? ""}`}>
                  <b>{category.rank ?? "-"}</b> {category.title}
                  {category.rate !== null ? ` · ${category.rate}%` : ""}
                </p>
              ))
            ) : (
              <p className="live-empty">{statusText(data.commerce.hotCategories.field)}</p>
            )}
          </div>
        </div>
      </Section>

      <Section
        title="合作数据概览"
        description="接单率/完单率/订单完成数按 30/90 天分开；统计时间范围按采集日推导"
      >
        <div className="live-inline-tabs">
          <button
            type="button"
            className={cooperationPeriod === "30" ? "active" : ""}
            onClick={() => setCooperationPeriod("30")}
          >
            近30天
          </button>
          <button
            type="button"
            className={cooperationPeriod === "90" ? "active" : ""}
            onClick={() => setCooperationPeriod("90")}
          >
            近90天
          </button>
        </div>
        <p className="live-source-note">
          时间范围：{formatRange(observedAt, cooperationPeriod === "30" ? 30 : 90)}（按观测日推算）
        </p>
        <div className="live-kpi-grid live-kpi-grid-compact">
          <Metric label="接单率" field={coop.accept} format={formatPercent} />
          <Metric label="完单率" field={coop.complete} format={formatPercent} />
          <Metric label="订单完成数" field={coop.completed} format={formatCount} />
        </div>
      </Section>

      <Section
        title="客户评价"
        description="多条评价分页保存；隐藏评价不展示原始订单名；信用评分与近30天信用分是不同字段"
        extra={<span className="live-count-badge">共 {formatCount(data.cooperation.total.value)} 条</span>}
      >
        {data.cooperation.reviewItems.length ? (
          <>
            <div className="live-kpi-grid live-kpi-grid-compact">
              <Metric label="综合星级" field={data.cooperation.summary} format={() => formatScore((data.cooperation.summary.value as Record<string, unknown> | null)?.comprehensive)} />
              <Metric label="作品质量" field={data.cooperation.summary} format={() => formatScore((data.cooperation.summary.value as Record<string, unknown> | null)?.content_quality)} />
              <Metric label="合作体验" field={data.cooperation.summary} format={() => formatScore((data.cooperation.summary.value as Record<string, unknown> | null)?.cooperation)} />
              <Metric label="信用评分" field={data.cooperation.summary} format={() => formatScore((data.cooperation.summary.value as Record<string, unknown> | null)?.credit)} />
            </div>
            <div className="live-review-list">
              {reviewRows.map((review) => (
                <article key={review.reviewKey} className="live-review">
                  <div className="live-review-head">
                    <strong>{review.reviewerLabel}</strong>
                    <span>{formatDate(review.occurredAt)}</span>
                  </div>
                  <div className="live-review-scores">
                    <span>综合评分 {formatScore(review.comprehensive)}</span>
                    <span>作品质量 {formatScore(review.contentQuality)}</span>
                    <span>合作体验 {formatScore(review.cooperation)}</span>
                    <span>信用评分 {formatScore(review.credit)}</span>
                  </div>
                  {review.content ? <p>{review.content}</p> : <p className="live-empty">该评价未填写文字内容</p>}
                  {review.contentRedacted && <small>评价中的联系方式已脱敏</small>}
                </article>
              ))}
            </div>
            <div className="live-pager">
              <button
                type="button"
                disabled={safeReviewPage <= 0}
                onClick={() => setReviewPage(Math.max(0, safeReviewPage - 1))}
              >
                上一页
              </button>
              <span>
                {safeReviewPage + 1}/{reviewPageCount}
              </span>
              <button
                type="button"
                disabled={safeReviewPage >= reviewPageCount - 1}
                onClick={() => setReviewPage(Math.min(reviewPageCount - 1, safeReviewPage + 1))}
              >
                下一页
              </button>
            </div>
          </>
        ) : (
          <div className="live-empty-block">
            <strong>暂无客户评价</strong>
            <span>
              {statusText(data.cooperation.reviews.field)}
              {data.cooperation.reviewMeta.total === 0 ? " · 评价总数 0" : ""}
            </span>
          </div>
        )}
      </Section>

      <p className="live-source-note live-bottom-note">
        数据来自磁力聚星直播详情快照；NO_DATA/FAILED/尚未采集分别展示，不用 0 或空值补造。
        {observedAt ? ` 观测于 ${formatDate(observedAt)}。` : ""}
      </p>
    </div>
  );
}

function CommerceBlock({ period }: { period: CommercePeriod }) {
  if (!isCollected(period.field.field) || period.zeroMeansNoData) {
    return (
      <div className="live-empty-block">
        <strong>暂无数据</strong>
        <span>
          {period.field.field?.status === "NO_DATA"
            ? "平台返回 0 或空结构，页面显示暂无可分析数据"
            : statusText(period.field.field)}
        </span>
      </div>
    );
  }
  return (
    <>
      <div className="live-kpi-grid live-kpi-grid-compact">
        <Metric label="带货直播场次" field={period.field} format={() => formatCount(period.liveCount)} />
        <Metric label="观看人数中位数" field={period.field} format={() => formatCount(period.watchMedian)} />
        <Metric label="最高在线人数中位数" field={period.field} format={() => formatCount(period.maxOnlineMedian)} />
        <Metric label="带货商品数量" field={period.field} format={() => formatCount(period.goodsCount)} />
      </div>
      <div className="live-goods-chart">
        <h4>带货分析：商品价格区间与带货量</h4>
        {period.graph.length ? (
          <BarChart items={period.graph} valueLabel="带货量" />
        ) : (
          <p className="live-empty">平台未提供带货分析数据</p>
        )}
      </div>
    </>
  );
}
