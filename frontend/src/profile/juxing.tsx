/**
 * 磁力聚星（快手）达人详情章节。
 *
 * 数据源只有一个：该入口自己的不可变快照 `profile_payload`（任务入口是本任务快照，达人库入口
 * 是该达人最新发布快照）。字段标签、单位与统计窗口来自聚星 verified registry 的字段目录；字段
 * 自身的 `period_label`（近30天 / 流量范围7天等）优先展示，缺失就是缺失，不补 0、不换算成星图口径。
 *
 * 这里刻意不把聚星的 `expected_cpm` 等指标塞进星图的 21–60 秒 / 60 秒以上两档字段：两者不是同一
 * 统计口径。作品只展示文本与计数，不把平台媒体地址当成作品落地页；画像只展示平台结构化原文，
 * 不在缺少页面证据时发明维度中文语义（字段语义映射属阶段 C/P1）。
 */
import { useMemo } from "react";
import { countText, unixSecondsText } from "../format";
import { fieldByKey } from "../snapshotCreator";
import { fieldView, periodSuffix } from "./views";
import { EmptyNote, FactRow, Panel } from "./ui";
import type { CatalogIndex } from "../fieldCatalog";

const BASIC_RAIL_FIELDS = [
  "platform_creator_id",
  "nickname",
  "avatar_uri",
  "province",
  "city",
  "followers",
  "monthly_follower_growth_count",
  "monthly_follower_growth_rate",
  "mcn_name",
  "introduction",
  "cooperation_offers",
  "gender",
  "profile_url",
  "content_form_labels",
];

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

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function number(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** The platform observation's own statistical window, when the contract did not register one. */
function observedPeriod(payload: Record<string, unknown>, fieldKey: string): string | null {
  return text(fieldByKey(payload, fieldKey)?.period_label);
}

function JuxingFieldFacts({
  payload,
  index,
  moduleKey,
  exclude = [],
  labelSuffix = {},
}: {
  payload: Record<string, unknown>;
  index: CatalogIndex;
  moduleKey: string;
  exclude?: string[];
  labelSuffix?: Record<string, string>;
}) {
  const fields = (record(payload.modules)?.[moduleKey] as Record<string, unknown> | undefined)?.fields;
  const entries = Array.isArray(fields)
    ? fields.filter((field): field is Record<string, unknown> => Boolean(record(field)))
    : [];
  const visible = entries.filter((field) => !exclude.includes(String(field.field_key ?? "")));
  if (!visible.length) return <EmptyNote>该模块本次没有可展示的字段。</EmptyNote>;
  return (
    <dl className="profile-facts">
      {visible.map((field) => {
        const key = String(field.field_key ?? "");
        const view = fieldView(payload, index, moduleKey, key);
        const note = [view.unit, observedPeriod(payload, key) ?? periodSuffix(view)]
          .filter(Boolean)
          .join(" · ");
        return (
          <FactRow
            key={key}
            label={`${view.label}${labelSuffix[key] ?? ""}`}
            note={note || undefined}
            value={view.collected && !view.blank ? view.text : (view.state ?? "—")}
            pending={!view.collected || view.blank}
          />
        );
      })}
    </dl>
  );
}

export function JuxingBasicPanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const offers = fieldView(payload, index, "basic", "cooperation_offers");
  const offerRows = offers.collected ? rows(offers.data) : [];
  return (
    <div className="profile-sections">
      <div className="profile-grid">
        <Panel title="基础资料" hint="昵称、头像、地区、粉丝与介绍见左侧资料卡；此处为其余平台字段。">
          <JuxingFieldFacts payload={payload} index={index} moduleKey="basic" exclude={BASIC_RAIL_FIELDS} />
        </Panel>
        <Panel
          title="视频报价"
          hint="平台整数 ÷ 1000 = 人民币元；原始整数与币种同时保留。"
          meta={offers.collected ? `${offerRows.length} 档` : offers.state ?? undefined}
        >
          {offerRows.length ? (
            <div className="juxing-offer-list">
              {offerRows.map((row, position) => {
                const duration = text(row.duration) ?? text(row.price_type_name) ?? `第 ${position + 1} 档`;
                const raw = number(row.platform_price_raw);
                const yuan = number(row.price_yuan);
                return (
                  <div key={`${duration}-${position}`} className="juxing-offer">
                    <strong>{duration}</strong>
                    <span>平台原值 {raw === null ? "暂无数据" : raw.toLocaleString("zh-CN")}</span>
                    <b>{yuan === null ? "未按整数档给出人民币值" : `${yuan.toLocaleString("zh-CN")} 元`}</b>
                    <small>{text(row.currency) ?? "币种暂无数据"}</small>
                    {number(row.original_price_raw) !== null && <small>原价 {number(row.original_price_yuan) === null ? `${number(row.original_price_raw)?.toLocaleString("zh-CN")}（平台原值）` : `${number(row.original_price_yuan)?.toLocaleString("zh-CN")} 元`}</small>}
                    {number(row.price_end_ms) !== null && <small>报价有效期至 {unixSecondsText(Math.floor((number(row.price_end_ms) ?? 0) / 1000))}</small>}
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyNote>{offers.collected ? "平台本次未返回可展示的报价。" : (offers.state ?? "暂无数据")}</EmptyNote>
          )}
        </Panel>
      </div>
    </div>
  );
}

export function JuxingSpreadPanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  return (
    <div className="profile-sections">
      <Panel
        title="传播表现"
        hint="平台原始值与统计窗口；CPM 单位以字段目录登记为准，不与星图两档报价等同。平台统计接口的平均点赞/评论/分享与页面「作品波动」卡按最近 15 个作品计算的口径不同，本页同时保留两者。"
      >
        <JuxingFieldFacts
          payload={payload}
          index={index}
          moduleKey="spread"
          labelSuffix={{
            average_like: "（统计接口）",
            average_comment: "（统计接口）",
            average_share: "（统计接口）",
          }}
        />
      </Panel>
    </div>
  );
}

export function JuxingWorksPanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const works = fieldView(payload, index, "works", "works");
  const items = works.collected ? rows(works.data) : [];
  // The platform's 「作品波动」 card shows the mean of the first 15 returned works; this is a
  // presentation-side calculation, not a new collection or a contract field.
  const sample = items.slice(0, 15);
  const mean = (key: string) => {
    const values = sample
      .map((row) => number(row[key]))
      .filter((value): value is number => value !== null);
    return values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : null;
  };
  const fluctuation = {
    play: mean("play_count"),
    like: mean("like_count"),
    comment: mean("comment_count"),
    share: mean("share_count"),
  };
  return (
    <div className="profile-sections">
      <Panel
        title="代表及近期作品"
        hint="封面来自平台返回的 coverUrl；平台未提供可验证的公开作品落地页，因此不构造作品链接。作品标识仅展示平台原值。"
        meta={works.collected ? `${items.length} 条` : works.state ?? undefined}
      >
        {items.length ? (
          <>
          <dl className="profile-facts compact">
            <FactRow
              label="作品波动（最近15个作品平均）"
              note="按平台页面口径计算"
              value={`播放 ${fluctuation.play === null ? "—" : countText(fluctuation.play)} · 点赞 ${fluctuation.like === null ? "—" : countText(fluctuation.like)} · 评论 ${fluctuation.comment === null ? "—" : countText(fluctuation.comment)} · 分享 ${fluctuation.share === null ? "—" : countText(fluctuation.share)}`}
            />
          </dl>
          <div className="juxing-work-list">
            {items.map((row, position) => {
              const published = number(row.published_at_ms);
              return (
                <div key={`${String(row.platform_content_id ?? "")}-${position}`} className="juxing-work">
                  <div className="juxing-work-head">
                    {text(row.cover_url) ? <img src={text(row.cover_url) ?? ""} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <div className="juxing-work-cover-empty"><span>封面暂无数据</span></div>}
                    <div className="juxing-work-copy">
                      <strong>{text(row.title) ?? "未提供作品标题"}</strong>
                      <small>{published === null ? "发布时间暂无数据" : unixSecondsText(Math.floor(published / 1000))}</small>
                      {(text(row.product_name) || row.contains_paid === true || row.quality_hot === true || row.quantity_hot === true || row.quality_and_quantity_hot === true || (text(row.first_industry_name) && text(row.first_industry_name) !== "未知")) && <div className="juxing-work-badges">
                        {text(row.product_name) && <span>带货商品：{text(row.product_name)}</span>}
                        {row.contains_paid === true && <span>含付费</span>}
                        {row.quality_hot === true && <span>优质</span>}
                        {row.quantity_hot === true && <span>高量</span>}
                        {row.quality_and_quantity_hot === true && <span>优质高量</span>}
                        {text(row.first_industry_name) && text(row.first_industry_name) !== "未知" && <span>{text(row.first_industry_name)}</span>}
                      </div>}
                    </div>
                  </div>
                  <dl>
                    <div><dt>播放</dt><dd>{countText(row.play_count)}</dd></div>
                    <div><dt>点赞</dt><dd>{countText(row.like_count)}</dd></div>
                    <div><dt>评论</dt><dd>{countText(row.comment_count)}</dd></div>
                    <div><dt>转发</dt><dd>{countText(row.share_count)}</dd></div>
                  </dl>
                </div>
              );
            })}
          </div>
          </>
        ) : (
          <EmptyNote>{works.collected ? "平台本次未返回作品。" : (works.state ?? "暂无数据")}</EmptyNote>
        )}
      </Panel>
    </div>
  );
}

const PORTRAIT_DIMENSIONS: Array<{ key: string; label: string }> = [
  { key: "sexPercentage", label: "性别" },
  { key: "agePercentage", label: "年龄" },
  { key: "areaPercentage", label: "地域（省份）" },
  { key: "cityPercentage", label: "城市" },
  { key: "interestPercentage", label: "兴趣" },
  { key: "activityPercentage", label: "活跃度" },
  { key: "mobileBrandPercentage", label: "手机品牌" },
  { key: "mobilePricePercentage", label: "手机价格" },
  { key: "nineMajorGroupsPercentage", label: "九大人群" },
  { key: "areaTopWithRadio", label: "地域 TOP 占比" },
  { key: "areaTopWithPermeation", label: "地域 TOP 渗透" },
];

function portraitRows(data: Record<string, unknown>, key: string) {
  const value = data[key];
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const row = record(item);
      if (!row) return null;
      const label = text(row.label);
      const ratio = number(row.value);
      if (label === null || ratio === null) return null;
      return { label, ratio, tgi: number(row.tgi) };
    })
    .filter((item): item is { label: string; ratio: number; tgi: number | null } => item !== null)
    .sort((left, right) => right.ratio - left.ratio);
}

function PortraitDistributions({ data }: { data: Record<string, unknown> }) {
  const dimensions = PORTRAIT_DIMENSIONS.map((dimension) => ({ ...dimension, rows: portraitRows(data, dimension.key) })).filter((dimension) => dimension.rows.length);
  if (!dimensions.length) return <EmptyNote>平台返回空画像结构。</EmptyNote>;
  return <div className="juxing-portrait-grid">
    {dimensions.map((dimension) => {
      const visible = dimension.rows.slice(0, 6);
      return <section className="juxing-portrait-dim" key={dimension.key}>
        <h4>{dimension.label}</h4>
        <table>
          <thead><tr><th>取值</th><th>占比</th><th>TGI</th></tr></thead>
          <tbody>
            {visible.map((row) => <tr key={`${dimension.key}-${row.label}`}><td>{row.label}</td><td>{(row.ratio * 100).toFixed(1)}%</td><td>{row.tgi === null ? "—" : row.tgi}</td></tr>)}
          </tbody>
        </table>
        {dimension.rows.length > visible.length && <details><summary>其余 {dimension.rows.length - visible.length} 项</summary>{dimension.rows.slice(6).map((row) => <div className="juxing-portrait-extra" key={`${dimension.key}-all-${row.label}`}><span>{row.label}</span><b>{(row.ratio * 100).toFixed(1)}%</b><em>TGI {row.tgi === null ? "—" : row.tgi}</em></div>)}</details>}
      </section>;
    })}
  </div>;
}

export function JuxingAudiencePanel({ payload, index }: { payload: Record<string, unknown>; index: CatalogIndex }) {
  const portraits = useMemo(
    () =>
      ["fan_portrait", "viewer_portrait"].map((key) => {
        const view = fieldView(payload, index, "audience", key);
        const data = record(view.data);
        return { key, view, data };
      }),
    [payload, index],
  );
  return (
    <div className="profile-sections">
      <div className="profile-grid">
        {portraits.map(({ key, view, data }) => (
          <Panel
            key={key}
            title={view.label}
            hint={`统计窗口：${observedPeriod(payload, key) ?? periodSuffix(view) ?? "平台未提供"}`}
            meta={view.collected ? (data ? `${Object.keys(data).length} 个维度` : "平台返回空结构") : (view.state ?? undefined)}
          >
            {view.collected && data ? (
              <div className="juxing-portrait-body">
                <PortraitDistributions data={data} />
                <details className="juxing-portrait">
                  <summary>查看平台原始结构</summary>
                  <pre>{JSON.stringify(data, null, 2)}</pre>
                </details>
              </div>
            ) : (
              <EmptyNote>{view.collected ? "平台返回空结构。" : (view.state ?? "暂无数据")}</EmptyNote>
            )}
          </Panel>
        ))}
      </div>
    </div>
  );
}
