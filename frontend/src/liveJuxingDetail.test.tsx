import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach } from "vitest";
import { describe, expect, it } from "vitest";
import { buildJuxingLiveModel } from "./liveJuxingModel";
import { JuxingLiveSections } from "./liveJuxingDetail";

type Envelope = Record<string, unknown>;

function numberField(key: string, value: number, unit: string, period?: string): Envelope {
  return {
    field_key: key,
    status: "COLLECTED",
    value: { kind: "number", amount: String(value), bound: "exact" },
    raw_value: String(value),
    unit,
    ...(period ? { period_label: period } : {}),
  };
}

function textField(key: string, value: string): Envelope {
  return { field_key: key, status: "COLLECTED", value, raw_value: value };
}

function tagsField(key: string, values: string[]): Envelope {
  return { field_key: key, status: "COLLECTED", value: values, raw_value: JSON.stringify(values) };
}

function structuredField(key: string, data: unknown, period?: string): Envelope {
  return {
    field_key: key,
    status: "COLLECTED",
    value: { kind: "structured", data },
    raw_value: JSON.stringify(data),
    ...(period ? { period_label: period } : {}),
  };
}

function noData(key: string, raw?: unknown): Envelope {
  return { field_key: key, status: "NO_DATA", ...(raw === undefined ? {} : { raw_value: JSON.stringify(raw) }) };
}

const work = {
  stream_id: "15046311215",
  collection_kind: "personal",
  title: "福利主播来了",
  cover_url: "https://example.test/cover.jpg",
  media_url: "https://example.test/replay.m3u8",
  published_at: "2026-11-05T12:00:00+08:00",
  duration_seconds: 5523,
  view_count: 1099630,
  peak_online_count: 63543,
  like_count: 4087340,
  comment_count: 50668,
  share_count: 2878,
  has_sku_info: true,
  order_id: "0",
};

const commercialWork = {
  ...work,
  stream_id: "15047054415",
  title: "聚星直播",
  has_sku_info: false,
  order_id: "1313921741704737653",
};

const review = {
  review_key: "review-1",
  comprehensive: 5,
  content_quality: 5,
  cooperation: 5,
  credit: 5,
  content: "遵守脚本约定，联系顺畅",
  content_redacted: false,
  occurred_at: "2022-10-31T13:22:00+08:00",
  reviewer_label: "匿名评论",
  promotion_type: 2,
  have_agent: false,
};

function payload(): Record<string, unknown> {
  return {
    modules: {
      basic: {
        status: "COLLECTED",
        fields: [
          textField("platform_creator_id", "52022133"),
          textField("platform_star_id", "9104"),
          textField("nickname", "王者荣耀王小贱（福利主播）"),
          textField("avatar_uri", "https://example.test/avatar.jpg"),
          textField("province", "广东"),
          textField("city", "广州"),
          numberField("followers", 37388604, "count"),
          tagsField("content_type_labels", ["游戏", "MOBA"]),
          tagsField("industry_labels", ["通信-号卡", "游戏-角色扮演"]),
          textField("mcn_name", "胡子家族"),
          textField("verified_info", "快手2025百大主播"),
          noData("content_form_labels", []),
        ],
      },
      live: {
        status: "COLLECTED",
        fields: [
          numberField("live.expect_viewer", 1734393, "count"),
          numberField("live.max_online", 129037, "count"),
          numberField("live.expect_cpm", 17, "cpm"),
          numberField("live.weekly_sessions", 10, "count"),
          noData("live.credit_score", null),
          numberField("live.expect_max_online", 52357, "count"),
          tagsField("live.cooperation_industries", ["游戏", "电商平台"]),
          tagsField("live.viewer_feature_tags", ["男性观众为主，占比76.6%"]),
          tagsField("live.viewer_device_tags", ["安卓设备为主，占比67.5%"]),
          tagsField("live.viewer_area_tags", ["广东、河南、山东的观众居多"]),
          structuredField("live.quote_details", [
            {
              page_label: "按小时/1小时",
              price_type_name: "直播按小时",
              price_yuan: 29100,
              price_raw: 29100000,
              currency: "CNY",
              original_price_yuan: null,
            },
            {
              page_label: "按天/1天",
              price_type_name: "直播按天",
              price_yuan: 75450,
              price_raw: 75450000,
              currency: "CNY",
              original_price_yuan: null,
            },
          ]),
          numberField("live.accept_order_rate_30d", 0.5641, "ratio", "近30天"),
          numberField("live.complete_order_rate_30d", 0.72, "ratio", "近30天"),
          numberField("live.completed_orders_30d", 18, "count", "近30天"),
          numberField("live.accept_order_rate_90d", 0.7363, "ratio", "近90天"),
          numberField("live.complete_order_rate_90d", 0.8451, "ratio", "近90天"),
          numberField("live.completed_orders_90d", 60, "count", "近90天"),
          numberField("live.avg_people", 847557, "count"),
          numberField("live.avg_like", 0, "count"),
          numberField("live.week_release", 8, "count"),
          numberField("live.interaction_rate", 2.4677, "ratio"),
        ],
      },
      fans_trend: {
        status: "COLLECTED",
        fields: [
          numberField("live.follower_growth_30d", 15674, "count", "近30天"),
          numberField("live.follower_growth_rate_30d", 0.0004, "ratio", "近30天"),
          structuredField(
            "live.follower_trend_30d",
            {
              period_days: 30,
              total_series: [
                { raw_label: "20261006", date: "2026-10-06", value: 37372930 },
                { raw_label: "20261007", date: "2026-10-07", value: 37380000 },
              ],
              increment_series: [
                { raw_label: "20261007", date: "2026-10-07", value: 7070 },
              ],
            },
            "近30天",
          ),
          numberField("live.follower_growth_90d", 636509, "count", "近90天"),
          numberField("live.follower_growth_rate_90d", 0.0173, "ratio", "近90天"),
          structuredField(
            "live.follower_trend_90d",
            {
              period_days: 90,
              total_series: [{ raw_label: "20260807", date: "2026-08-07", value: 36752095 }],
              increment_series: [{ raw_label: "20260808", date: "2026-08-08", value: 39304 }],
            },
            "近90天",
          ),
        ],
      },
      index: {
        status: "COLLECTED",
        fields: [
          numberField("live.index_score", 81.6, "score"),
          structuredField("live.index_dimensions", {
            current: [
              { key: "starIndex", label: "达人指数", value: 81.6 },
              { key: "addFansIndex", label: "涨粉指数", value: 92.09 },
              { key: "performancePriceIndex", label: "性价比", value: 49.48 },
              { key: "createIndex", label: "影响力", value: 89.92 },
              { key: "bizActiIndex", label: "商业活跃度", value: 89.72 },
              { key: "coopIndex", label: "合作指数", value: 94 },
            ],
            same_fans_segment_avg: [{ key: "addFansIndex", label: "涨粉指数", value: 91.1 }],
            missing_avg_dimensions: ["starIndex"],
            selectable: ["starIndex", "addFansIndex"],
          }),
          numberField("live.index_industry_rank", 30538, "count"),
          numberField("live.index_industry_percent", 0.7832, "ratio"),
          numberField("live.index_fans_rank", 64, "count"),
          numberField("live.index_fans_percent", 0.3905, "ratio"),
          structuredField("live.index_trend", {
            all_zero: true,
            selectable: ["starIndex", "addFansIndex"],
            series: [
              {
                key: "starIndex",
                label: "达人指数",
                points: [
                  { period: "2026-10", value: 0 },
                  { period: "2026-11", value: 0 },
                ],
              },
            ],
          }),
        ],
      },
      works: {
        status: "COLLECTED",
        fields: [
          structuredField("live.personal_live_works", [work], "近30天"),
          structuredField("live.commercial_live_works", [commercialWork]),
          structuredField("live.recent_live_works", [work], "最近15个直播"),
          structuredField(
            "live.live_frequency",
            {
              modes: {
                month: { label: "按月", items: [{ key: "9", label: "9月", value: 33 }] },
                week: { label: "按周", items: [{ key: "0", label: "周日", value: 15 }] },
                hour: { label: "按时", items: [{ key: "19", label: "19时", value: 41 }] },
              },
            },
            "近三个月",
          ),
        ],
      },
      audience: {
        status: "COLLECTED",
        fields: [
          structuredField("live.viewer_portrait", {
            side: "viewer",
            gender: [{ raw_label: "男性", label: "男性", value: 0.766, tgi: 146 }],
            age: [{ raw_label: "18-23", label: "18-23", value: 0.383, tgi: 336 }],
            device_brand: [{ raw_label: "华为", label: "华为", value: 0.211, tgi: 73 }],
            device_price: [{ raw_label: "1000-2000", label: "1000-2000", value: 0.393, tgi: 89 }],
            device_type: [],
            activity: [{ raw_label: "超高活", label: "超高活", value: 0.512, tgi: 132 }],
            city_tier: [{ raw_label: "thirdline", label: "三线", value: 0.296, tgi: 125 }],
            city: [{ raw_label: "重庆", label: "重庆", value: 0.015, tgi: 96 }],
            province: [{ raw_label: "广东", label: "广东", value: 0.114, tgi: 156 }],
            province_share: [{ raw_label: "广东", label: "广东", value: 0.114, tgi: 156 }],
            province_penetration: [{ raw_label: "江西", label: "江西", value: 0.036, tgi: null }],
            interest: [],
            nine_major_groups: [],
            availability: {
              device_type: "SUMMARY_ONLY",
              interest: "NO_DATA",
              nine_major_groups: "NO_DATA",
            },
          }),
          structuredField("live.fan_portrait", {
            side: "fan",
            gender: [{ raw_label: "女性", label: "女性", value: 0.607, tgi: 144 }],
            interest: [{ raw_label: "运动", label: "运动", value: 0.825, tgi: 98 }],
            availability: { interest: "COLLECTED" },
          }),
        ],
      },
      commerce: {
        status: "COLLECTED",
        fields: [
          noData("live.commerce_7d", {
            liveCnt: 0,
            liveWatchCntMedian: 0,
            liveMaxOnlineCntMedian: 0,
            goodsCnt: 0,
            goodsGraph: [],
          }),
          structuredField(
            "live.commerce_30d",
            {
              period_days: 30,
              live_cnt: 4,
              live_watch_cnt_median: 2313723,
              live_max_online_cnt_median: 45708,
              goods_cnt: 14,
              goods_graph: [{ range: "100+", count: 77 }],
              zero_means_no_data: false,
            },
            "近30日",
          ),
          structuredField(
            "live.commerce_90d",
            {
              period_days: 90,
              live_cnt: 12,
              live_watch_cnt_median: 2893961,
              live_max_online_cnt_median: 52297,
              goods_cnt: 35,
              goods_graph: [{ range: "5-10", count: 80930 }],
              zero_means_no_data: false,
            },
            "近90日",
          ),
          structuredField("live.hot_brands", [
            { brand_id: 42119, title: "王者荣耀", rank: 1 },
          ]),
          structuredField("live.hot_categories", [
            { category_id: 0, title: "其他", rate: 100, rank: 1 },
          ]),
        ],
      },
      cooperation: {
        status: "COLLECTED",
        fields: [
          structuredField("live.evaluation_summary", {
            comprehensive: 4.8,
            content_quality: 4.8,
            cooperation: 4.8,
            credit: 4.8,
            total_reviews: 18,
          }),
          numberField("live.evaluation_total", 18, "count"),
          structuredField("live.evaluation_reviews", {
            total: 18,
            collected: 18,
            pages: 2,
            complete: true,
            items: [review],
          }),
        ],
      },
    },
  };
}

afterEach(cleanup);

describe("juxing live detail model", () => {
  it("reads statuses, structures, works and evaluation while keeping no-data apart", () => {
    const model = buildJuxingLiveModel(payload());
    expect(model.basic.nickname.value).toBe("王者荣耀王小贱（福利主播）");
    expect(model.basic.contentTypes.value).toEqual(["游戏", "MOBA"]);
    expect(model.quotes).toHaveLength(2);
    expect(model.overview.maxOnline.value).toBe(129037);
    expect(model.overview.creditScore.status).toBe("NO_DATA");
    expect(model.overview.expectMaxOnline.value).toBe(52357);
    expect(model.works.personalItems).toHaveLength(1);
    expect(model.works.commercialItems[0]?.hasSkuInfo).toBe(false);
    expect(model.works.frequencyModes.month?.items[0]?.value).toBe(33);
    expect(model.fans["30"].totalSeries[0]?.label).toBe("2026-10-06");
    expect(model.index.current[0]?.label).toBe("达人指数");
    expect(model.index.industryRank.value).toBe(30538);
    expect(model.audience.viewerSide?.dimensions.city_tier[0]?.label).toBe("三线");
    expect(model.audience.viewerSide?.availability.device_type).toBe("SUMMARY_ONLY");
    expect(model.commerce.periods["7"].field.status).toBe("NO_DATA");
    expect(model.commerce.periods["30"].liveCount).toBe(4);
    expect(model.cooperation.reviewItems).toHaveLength(1);
    expect(model.cooperation.reviewMeta.total).toBe(18);
    expect(model.isLegacy).toBe(false);
  });

  it("marks a payload without the new modules as legacy", () => {
    const model = buildJuxingLiveModel({
      modules: {
        basic: { status: "COLLECTED", fields: [textField("nickname", "旧达人")] },
        live: { status: "COLLECTED", fields: [numberField("live.max_online", 12, "count")] },
      },
    });
    expect(model.isLegacy).toBe(true);
    expect(model.basic.nickname.value).toBe("旧达人");
    expect(model.works.personal.status).toBe("MISSING");
  });

  it("uses the current successful live metric only as an explicitly marked fallback", () => {
    const value = payload();
    const live = value.modules as Record<string, { fields: Envelope[] }>;
    live.live.fields = live.live.fields.filter((field) => field.field_key !== "live.max_online");
    const model = buildJuxingLiveModel(value, {
      "live.max_online": {
        status: "COLLECTED",
        value: { kind: "number", amount: "77" },
        unit: "count",
      },
    });
    expect(model.overview.maxOnline.value).toBe(77);
    expect(model.overview.maxOnline.fallback).toBe(true);
  });
});

describe("juxing live detail sections", () => {
  it("renders the business modules and real values", () => {
    render(<JuxingLiveSections payload={payload()} observedAt="2026-11-05T12:00:00+08:00" />);
    expect(screen.getByText("基础信息与直播报价")).toBeInTheDocument();
    expect(screen.getByText("¥29,100")).toBeInTheDocument();
    expect(screen.getAllByText("达人指数").length).toBeGreaterThan(0);
    expect(screen.getByText("30,538")).toBeInTheDocument();
    expect(screen.getByText("个人作品")).toBeInTheDocument();
    expect(screen.getByText("近30天涨粉数")).toBeInTheDocument();
    expect(screen.getAllByText("观众画像").length).toBeGreaterThan(0);
    expect(screen.getByText("带货数据")).toBeInTheDocument();
    expect(screen.getByText("接单率")).toBeInTheDocument();
    expect(screen.getByText("综合星级")).toBeInTheDocument();
    expect(screen.getByText("匿名评论")).toBeInTheDocument();
    expect(screen.getAllByText("暂无数据").length).toBeGreaterThan(0);
  });

  it("switches work collections, ecommerce filter, frequency mode and commerce period", () => {
    render(<JuxingLiveSections payload={payload()} observedAt="2026-11-05T12:00:00+08:00" />);
    fireEvent.click(screen.getAllByRole("button", { name: "聚星作品" })[0]);
    expect(screen.getByText("聚星直播")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "只看电商带货" }));
    expect(screen.getByText(/当前无电商带货作品/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "按月" }));
    fireEvent.click(screen.getByRole("button", { name: "按周" }));
    expect(screen.getByText(/周 0=周日/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "近30日" }));
    expect(screen.getByText(/2,313,723/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "近90天" })[1]);
    expect(screen.getAllByText(/84.5%/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "城市" }));
    expect(screen.getByText("重庆")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "省份" }));
    fireEvent.click(screen.getByRole("button", { name: "渗透" }));
    expect(screen.getByText("江西")).toBeInTheDocument();
  });

  it("shows the legacy banner when new modules are absent", () => {
    render(
      <JuxingLiveSections
        payload={{
          modules: {
            basic: { status: "COLLECTED", fields: [textField("nickname", "旧达人")] },
            live: { status: "COLLECTED", fields: [numberField("live.max_online", 12, "count")] },
          },
        }}
      />,
    );
    expect(screen.getByText(/尚未按新版字段采集/)).toBeInTheDocument();
    expect(screen.getAllByText(/尚未采集/).length).toBeGreaterThan(0);
  });
});
