/**
 * Xingtu live-detail sections.
 *
 * Kept separate from the shared `LiveCreatorDetailView` so the Juxing live-detail work and this
 * Xingtu field work can evolve independently; the parent selects the platform-specific component.
 * Every value is read from the stored snapshot envelope; nothing is mocked or inferred.
 */
import { useMemo, useState } from "react";
import { countText } from "./format";
import { DistributionBars, EmptyNote, TrendLine } from "./profile/ui";
import {
  audienceData,
  audienceTypes,
  basicList,
  basicText,
  calibreEntries,
  calendarData,
  crowdTypes,
  distributionItems,
  distributionTop10,
  fieldsOf,
  introductionText,
  latestData,
  metricLabel,
  metricNote,
  metricText,
  moduleFallback,
  overviewTypes,
  pickCalibre,
  pricingServices,
  roomDurationText,
  roomMetric,
  roomTitle,
  roomTypeText,
  roomsData,
  type CalibreData,
  type CalendarData,
  type JsonRecord,
  type MetricEnvelope,
  type OverviewData,
  type RoomRow,
} from "./liveDetail";
import type { LiveMetricEnvelope } from "./types";

const modeLabels: Record<string, string> = {
  per_day: "按天",
  per_hour: "按小时",
  per_goods: "按商品",
  unknown: "平台未标明",
};

function Section({
  title,
  hint,
  meta,
  children,
}: {
  title: string;
  hint?: string;
  meta?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel library-detail-panel live-detail-panel">
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {hint ? <p>{hint}</p> : null}
        </div>
        {meta ? <span>{meta}</span> : null}
      </div>
      <div className="live-detail-body">{children}</div>
    </section>
  );
}

function MetricGrid({
  metrics,
  order,
  note,
}: {
  metrics: Record<string, MetricEnvelope>;
  order: string[];
  note?: string | null;
}) {
  return (
    <div className="live-metric-grid">
      {order.map((key) => {
        const metric = metrics[key];
        const noteText = metricNote(metric);
        return (
          <div className="live-metric" key={key}>
            <span>{metricLabel(key)}</span>
            <strong>{metricText(metric)}</strong>
            {noteText ? <small>{noteText}</small> : null}
          </div>
        );
      })}
      {note ? <p className="live-metric-note">{note}</p> : null}
    </div>
  );
}

function RoomMini({ room, label }: { room: RoomRow | null | undefined; label: string }) {
  if (!room) return null;
  return (
    <div className="live-room-mini">
      <span>{label}</span>
      <strong>{roomTitle(room)}</strong>
      <small>{room.start_time ? room.start_time.slice(0, 16).replace("T", " ") : "开播时间未提供"}</small>
      <div>
        <b>观看人次 {metricText(roomMetric(room, "watch_cnt"))}</b>
        <b>ACU {metricText(roomMetric(room, "acu"))}</b>
        <b>PCU {metricText(roomMetric(room, "pcu"))}</b>
        <b>评论率 {metricText(roomMetric(room, "comment_rate"))}</b>
      </div>
    </div>
  );
}

type CalendarMonthData = NonNullable<CalendarData["months"]>[number];

function CalendarMonth({ month }: { month: CalendarMonthData | null }) {
  if (!month) return <EmptyNote>平台未返回该月月历数据。</EmptyNote>;
  const days = month.days ?? [];
  const byDate = new Map(days.map((day) => [day.date, day.rooms]));
  const label = month.month_label ?? `${month.year ?? ""}-${month.month ?? ""}`;
  const first = days[0]?.date ?? `${month.year ?? ""}-${String(month.month ?? "").padStart(2, "0")}-01`;
  const weekday = new Date(`${first}T00:00:00+08:00`).getDay();
  const cells: Array<{ date: string; rooms: RoomRow[] } | null> = [];
  for (let index = 0; index < weekday; index += 1) cells.push(null);
  for (let day = 1; day <= 31; day += 1) {
    const date = `${String(month.year ?? "").padStart(4, "0")}-${String(month.month ?? "").padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const parsed = new Date(`${date}T00:00:00+08:00`);
    if (Number.isNaN(parsed.getTime()) || parsed.getMonth() + 1 !== month.month) break;
    cells.push({ date, rooms: byDate.get(date) ?? [] });
  }
  return (
    <div className="live-calendar">
      <div className="live-calendar-head">
        <strong>{label}</strong>
        <span>当月 {month.room_count ?? 0} 场 · 已采集 {days.length} 个开播日</span>
      </div>
      <div className="live-calendar-grid live-calendar-weekdays">
        {["一", "二", "三", "四", "五", "六", "日"].map((day) => <span key={day}>{day}</span>)}
      </div>
      <div className="live-calendar-grid">
        {cells.map((cell, index) => (
          <div className={`live-calendar-day${cell?.rooms.length ? " active" : ""}`} key={`${cell?.date ?? "blank"}-${index}`}>
            <span>{cell?.date ? Number(cell.date.slice(-2)) : ""}</span>
            {cell?.rooms.length ? <b>{cell.rooms.length} 场</b> : null}
          </div>
        ))}
      </div>
      <div className="live-calendar-rooms">
        {days.length ? days.flatMap((day) => day.rooms.map((room) => (
          <div className="live-calendar-room" key={`${day.date}-${room.room_id}`}>
            <strong>{day.date}</strong>
            <span>{roomTitle(room)}</span>
            <small>{metricText(roomMetric(room, "watch_cnt"))} 观看人次 · {metricText(roomMetric(room, "acu"))} ACU</small>
          </div>
        ))) : <EmptyNote>当前月没有平台返回的直播场次。</EmptyNote>}
      </div>
    </div>
  );
}

export function XingtuLiveSections({
  platformCreatorId,
  payload,
  observedAt,
  scopeLabel,
}: {
  platformCreatorId: string;
  payload?: Record<string, unknown>;
  liveMetrics?: Record<string, LiveMetricEnvelope>;
  observedAt?: string | null;
  scopeLabel: string;
}) {
  const data = payload ?? {};
  const basic = fieldsOf(data, "basic");
  const types = useMemo(
    () => (overviewTypes(data).length ? overviewTypes(data) : [{ key: "general", label: "不限" }]),
    [data],
  );
  const [selectedType, setSelectedType] = useState<string>("");
  const activeType = types.some((item) => item.key === selectedType) ? selectedType : types[0]?.key ?? "general";
  const overviewField = fieldsOf(data, "live_overview")[`overview.${activeType}`];
  const overviewValue = overviewField?.value as JsonRecord | undefined;
  const overview = overviewValue?.kind === "structured" ? ((overviewValue.data as OverviewData) ?? null) : null;
  const calibres = calibreEntries(overview);
  const [selectedCalibre, setSelectedCalibre] = useState<string>("");
  const currentCalibre = calibres.find((item) => item.key === selectedCalibre)?.data ?? pickCalibre(overview, null, null, false);
  const fallbackOverview = moduleFallback(data, "live_overview");
  const fallbackAnalysis = moduleFallback(data, "live_analysis");
  const fallbackAudience = moduleFallback(data, "live_audience");
  const fallbackPricing = moduleFallback(data, "live_pricing");
  const pricing = pricingServices(data);
  const calendar = calendarData(data, activeType);
  const latest = latestData(data, activeType);
  const rooms = roomsData(data);
  const [monthIndex, setMonthIndex] = useState(0);
  const months = calendar?.months ?? [];
  const month = months[Math.min(monthIndex, Math.max(0, months.length - 1))] ?? null;
  const [latestMetric, setLatestMetric] = useState<"watch_cnt" | "acu" | "pcu">("watch_cnt");
  const latestSeries = (latest?.series?.[latestMetric] ?? [])
    .filter((point) => point.status === "COLLECTED" && point.value !== null && point.value !== undefined)
    .map((point) => ({
      label: point.date ? point.date.slice(5, 10) : String(point.index + 1),
      value: Number(point.value),
    }));
  const [roomLimit, setRoomLimit] = useState(20);
  const roomRows = (rooms?.rows ?? []).slice(0, roomLimit);
  const audienceTypeOptions = audienceTypes(data);
  const [selectedAudienceType, setSelectedAudienceType] = useState<string>("");
  const activeAudienceType = audienceTypeOptions.some((item) => item.key === selectedAudienceType)
    ? selectedAudienceType
    : audienceTypeOptions[0]?.key ?? activeType;
  const crowdOptions = crowdTypes(data, activeAudienceType);
  const [selectedCrowd, setSelectedCrowd] = useState<string>("");
  const activeCrowd = crowdOptions.some((item) => item.key === selectedCrowd) ? selectedCrowd : crowdOptions[0]?.key ?? "fans";
  const audience = audienceData(data, activeAudienceType, activeCrowd);
  const gallery = [
    ["gender", "性别分布"],
    ["age", "年龄分布"],
    ["province", "全国省份分布 TOP10"],
    ["city", "城市分布 TOP10"],
    ["city_level", "城市等级分布"],
    ["interest", "兴趣分布"],
    ["eight_crowds", "八大人群占比"],
    ["device", "设备分布"],
  ] as const;
  const basicRows: Array<{ label: string; value: string | null }> = [
    { label: "达人名称", value: basicText(data, "nickname") },
    { label: "性别", value: basicText(data, "gender") },
    { label: "所在地域", value: [basicText(data, "province"), basicText(data, "city")].filter(Boolean).join(" · ") || null },
    {
      label: "粉丝数",
      value: (() => {
        if (basic.followers?.status !== "COLLECTED") return null;
        const raw = basic.followers.value;
        const amount = raw && typeof raw === "object" && "amount" in raw
          ? (raw as { amount?: unknown }).amount
          : raw;
        return countText(amount);
      })(),
    },
    { label: "内容类型", value: basicText(data, "content_type") },
    { label: "内容标签", value: basicList(data, "content_tags").join(" / ") || null },
    { label: "商单类型", value: basicList(data, "business_order_types").join(" / ") || null },
    { label: "抖音号", value: basicText(data, "douyin_id") },
    { label: "达人微信", value: basicText(data, "wechat") },
    { label: "星图 ID", value: platformCreatorId },
    { label: "所属机构", value: basicText(data, "mcn_name") },
  ];
  const avatar = basicText(data, "avatar_uri");
  const introduction = introductionText(data);
  const ecom = (currentCalibre?.groups?.ecom ?? {}) as Record<string, MetricEnvelope>;
  const convert = (currentCalibre?.groups?.convert ?? {}) as Record<string, MetricEnvelope>;
  const convertNote = typeof currentCalibre?.groups?.convert_note === "string" ? currentCalibre.groups.convert_note : null;

  return (
    <>
      <div className="live-detail-meta">
        <span>{scopeLabel}</span>
        {observedAt ? <span>观测于 {observedAt.slice(0, 19).replace("T", " ")}</span> : null}
        <span>直播与短视频指标不混用；空值/无权限不显示为 0。</span>
      </div>

      <Section title="基本资料" hint="平台主页公开资料；达人微信仅授权业务用户可见，介绍中的其他联系方式已脱敏。" meta={basic.nickname?.status ?? undefined}>
        <div className="live-basic-card">
          <div className="live-basic-avatar">{avatar ? <img src={avatar} alt="" /> : null}</div>
          <dl className="live-facts">
            {basicRows.map((row) => (
              <div key={row.label}><dt>{row.label}</dt><dd>{row.value || "暂无数据"}</dd></div>
            ))}
          </dl>
        </div>
        {introduction ? <p className="live-introduction">{introduction}</p> : <EmptyNote>平台未提供达人介绍。</EmptyNote>}
      </Section>

      <Section
        title="直播服务报价"
        hint="按服务分别保存；按天、按小时、按商品不会互相覆盖。"
        meta={fallbackPricing ?? (pricing.length ? `${pricing.length} 项` : undefined)}
      >
        {pricing.length ? (
          <div className="live-price-grid">
            {pricing.map((service, index) => (
              <div className="live-price-card" key={`${service.service_label}-${index}`}>
                <span>{service.service_label ?? "未命名服务"}</span>
                <strong>{service.price ? metricText(service.price) : "平台未提供"}</strong>
                <small>{service.unit ?? ""} · {modeLabels[service.pricing_mode ?? "unknown"]} · {service.currency ?? "CNY"}</small>
                {service.origin_price && service.origin_price.status === "COLLECTED" ? <em>原价 {metricText(service.origin_price)}</em> : null}
              </div>
            ))}
          </div>
        ) : <EmptyNote>平台未提供该达人的直播服务报价。</EmptyNote>}
      </Section>

      <Section
        title="数据概览"
        hint="按直播类型、周期和统计口径分别保存；切换不会混合数值。"
        meta={fallbackOverview ?? currentCalibre?.period_label ?? undefined}
      >
        <div className="live-toolbar">
          <div className="live-tabs">
            {types.map((item) => (
              <button className={item.key === activeType ? "active" : ""} key={item.key} onClick={() => { setSelectedType(item.key); setSelectedCalibre(""); }}>{item.label}</button>
            ))}
          </div>
          {calibres.length ? (
            <label className="live-calibre-select">
              口径
              <select value={selectedCalibre || calibres[0]?.key} onChange={(event) => setSelectedCalibre(event.target.value)}>
                {calibres.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.data.period_label ?? `近${item.data.period ?? "?"}天`} · {item.data.excluded_marketing ? "排除营销流量" : "不排除营销流量"} · {item.data.only_star_order ? "只看星图商单" : "全部商单"}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        {currentCalibre ? (
          <>
            <div className="live-interpretation">
              {Object.entries(currentCalibre.interpretation ?? {}).map(([key, metric]) => (
                <div key={key}><span>{metricLabel(key)}</span><strong>{metricText(metric)}</strong></div>
              ))}
              <small>{currentCalibre.period_label ?? `近${currentCalibre.period ?? "?"}天`} · {currentCalibre.excluded_marketing ? "已排除营销流量" : "未排除营销流量"} · {currentCalibre.only_star_order ? "只看星图商单" : "全部商单"}</small>
            </div>
            <h3 className="live-subtitle">直播间数据</h3>
            <MetricGrid metrics={(currentCalibre.groups?.room ?? {}) as Record<string, MetricEnvelope>} order={["room_cnt", "watch_ucnt_avg", "watch_cnt_avg", "acu", "pcu", "fans_watch_rate", "follow_ucnt_avg", "comment_rate_avg", "like_rate_avg", "watch_duration_avg", "interact_rate_avg", "acu_precede_percent"]} />
            <h3 className="live-subtitle">带货表现</h3>
            {activeType === "game" || activeType === "other" ? (
              <EmptyNote>带货表现仅对电商带货直播生效。</EmptyNote>
            ) : (
              <MetricGrid metrics={ecom} order={["ecom_live_product_num", "avg_gmv_range", "avg_ecom_product_price_range", "avg_gpm_range"]} />
            )}
            <h3 className="live-subtitle">转化表现</h3>
            {Object.keys(convert).length ? (
              <MetricGrid metrics={convert} order={["ctr_avg", "handle_ctr_avg", "snowflake_ctr_avg", "windmill_ctr_avg", "handle_cvr_avg"]} note={convertNote} />
            ) : <EmptyNote>转化表现仅对星图商单生效，平台当前未返回该口径数据。</EmptyNote>}
          </>
        ) : <EmptyNote>当前直播类型没有可展示的数据概览。平台可能未开放该类型，或本次采集未取得数据。</EmptyNote>}
      </Section>

      <Section
        title="直播分析"
        hint="月历为当前月（无直播时补采上月）；直播间列表为平台近90天全量分页，类型按 latest/detail 可用时登记。"
        meta={fallbackAnalysis ?? (months.length ? `${months.length} 个月` : undefined)}
      >
        <div className="live-toolbar">
          <div className="live-tabs">
            {months.map((item, index) => (
              <button className={index === monthIndex ? "active" : ""} key={item.month_label ?? index} onClick={() => setMonthIndex(index)}>{item.month_label ?? `第${index + 1}月`}</button>
            ))}
          </div>
        </div>
        <CalendarMonth month={month} />
        <div className="live-room-mini-grid">
          <RoomMini room={month?.highest_room} label="当月最高场观" />
          <RoomMini room={month?.latest_room} label="最近一场直播" />
        </div>
        <h3 className="live-subtitle">近 15 场直播表现</h3>
        <div className="live-toolbar">
          <div className="live-tabs">
            {([["watch_cnt", "观看人次"], ["acu", "ACU"], ["pcu", "PCU"]] as const).map(([key, label]) => (
              <button className={latestMetric === key ? "active" : ""} key={key} onClick={() => setLatestMetric(key)}>{label}</button>
            ))}
          </div>
        </div>
        {latestSeries.length ? <TrendLine points={latestSeries} ariaLabel={`近15场${latestMetric}趋势`} note={`平台原始点 ${latest?.window ?? latestSeries.length} 个`} /> : <EmptyNote>平台未返回近15场趋势数据。</EmptyNote>}
        <h3 className="live-subtitle">直播间列表</h3>
        {rooms?.rows?.length ? (
          <>
            <div className="live-rooms-table-wrap">
              <table className="live-rooms-table">
                <thead><tr><th>标题</th><th>开播时间</th><th>时长</th><th>直播类型</th><th>观看人数</th><th>观看人次</th><th>ACU</th><th>PCU</th><th>评论率</th><th>点赞率</th><th>CTR</th><th>GMV</th></tr></thead>
                <tbody>
                  {roomRows.map((row: RoomRow) => (
                    <tr key={row.room_id ?? `${row.title}-${row.start_time}`}>
                      <td>{roomTitle(row)}</td>
                      <td>{row.start_time ? row.start_time.slice(0, 16).replace("T", " ") : "—"}</td>
                      <td>{roomDurationText(row)}</td>
                      <td>{roomTypeText(row)}</td>
                      <td>{metricText(roomMetric(row, "watch_ucnt"))}</td>
                      <td>{metricText(roomMetric(row, "watch_cnt"))}</td>
                      <td>{metricText(roomMetric(row, "acu"))}</td>
                      <td>{metricText(roomMetric(row, "pcu"))}</td>
                      <td>{metricText(roomMetric(row, "comment_rate"))}</td>
                      <td>{metricText(roomMetric(row, "like_rate"))}</td>
                      <td>{metricText(roomMetric(row, "ctr"))}</td>
                      <td>{metricText(roomMetric(row, "gmv_range"))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="live-rooms-footer">
              <span>共 {rooms.pagination?.total_count ? String(rooms.pagination.total_count) : rooms.rows.length} 场；已入库 {rooms.rows.length} 场</span>
              {roomLimit < rooms.rows.length ? <button className="button ghost" onClick={() => setRoomLimit((value) => value + 20)}>显示更多</button> : null}
            </div>
          </>
        ) : <EmptyNote>平台未返回直播间列表。</EmptyNote>}
      </Section>

      <Section
        title="受众画像"
        hint="按直播类型和粉丝/观众分别保存；占比由平台计数计算，原始计数一并保留。"
        meta={fallbackAudience ?? (audience ? `合计 ${audience.distributions?.gender?.total ?? "—"}` : undefined)}
      >
        <div className="live-toolbar">
          <div className="live-tabs">
            {audienceTypeOptions.map((item) => (
              <button className={item.key === activeAudienceType ? "active" : ""} key={item.key} onClick={() => { setSelectedAudienceType(item.key); setSelectedCrowd(""); }}>{item.label}</button>
            ))}
          </div>
          <div className="live-tabs">
            {crowdOptions.map((item) => (
              <button className={item.key === activeCrowd ? "active" : ""} key={item.key} onClick={() => setSelectedCrowd(item.key)}>{item.label}</button>
            ))}
          </div>
        </div>
        {audience ? (
          <div className="live-audience-grid">
            {gallery.map(([key, title]) => {
              const distribution = audience.distributions?.[key];
              const values = key === "province" || key === "city" ? distributionTop10(audience, key) : distributionItems(audience, key);
              return (
                <div className="live-audience-card" key={key}>
                  <h3>{title}</h3>
                  {distribution?.description ? <p>{distribution.description}</p> : null}
                  {values.length ? <DistributionBars items={values} ariaLabel={title} /> : <EmptyNote>平台未返回该分布。</EmptyNote>}
                </div>
              );
            })}
          </div>
        ) : <EmptyNote>当前直播类型/画像类型没有可展示的受众画像。</EmptyNote>}
      </Section>
    </>
  );
}
