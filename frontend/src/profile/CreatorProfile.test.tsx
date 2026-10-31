import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CreatorProfile } from "./CreatorProfile";
import type {
  CreatorLibraryDetail,
  CreatorVideoObservation,
  CreatorVideoPage,
  ProfileFieldCatalog,
} from "../types";

const CATALOG: ProfileFieldCatalog = {
  platform: "douyin_xingtu",
  contract_version: "test",
  modules: [
    {
      key: "basic",
      fields: [
        field("nickname", "达人昵称", "text"),
        field("province", "省份", "text"),
        field("gender", "性别", "text"),
        field("introduction", "介绍", "text"),
        field("followers", "粉丝数", "number", { unit: "count" }),
        field("monthly_follower_growth_rate", "月涨粉率", "ratio", { unit: "ratio", period: "月" }),
      ],
    },
    {
      key: "fans",
      fields: [
        field("connection_funnel", "连接用户漏斗", "structured"),
        field("seeding_link_structure", "种草链路层级", "structured"),
        field("fans_daily_trend", "近30日连接用户总量趋势", "structured", {
          correction: "近30日粉丝总数趋势",
          source: "evidence_correction",
        }),
        field("connection_daily_trend", "近30日连接用户趋势", "structured"),
        field("monthly_connected_users", "月连接用户数", "number", { unit: "count", period: "月" }),
      ],
    },
    {
      key: "spread",
      fields: [
        field("interaction_rate", "互动率及同行超越", "structured"),
        field("item_rate_metrics", "作品传播比较指标", "structured"),
        field("play_median", "播放中位数", "structured"),
        field("completion_rate", "完播率及同行超越", "structured"),
        field("average_duration", "平均观看时长", "structured"),
        field("average_likes", "平均点赞", "structured"),
        field("average_comments", "平均评论", "structured"),
        field("average_shares", "平均分享", "structured"),
        field("expected_cpm", "预期 CPM", "structured"),
      ],
    },
    {
      key: "commercial",
      fields: [field("cooperation_offers", "合作形式与报价明细", "structured")],
    },
    {
      key: "creation",
      fields: [
        field("performance_descriptions", "视频表现口径说明", "structured"),
        field("recent_video_performance", "最新视频表现", "structured"),
      ],
    },
    {
      key: "fulfillment",
      fields: [
        field("credit_score", "信用分", "text"),
        field("industry_order_distribution", "行业订单分布", "structured"),
        field("industry_play_distribution", "行业播放分布", "structured"),
        field("cooperation_industry_distribution", "合作行业分布", "structured"),
      ],
    },
  ],
};

function field(
  key: string,
  name: string,
  kind: string,
  options: { unit?: string; period?: string; source?: "contract" | "evidence_correction"; correction?: string } = {},
) {
  return {
    key,
    name: options.correction ?? name,
    contract_name: name,
    name_source: options.source ?? ("contract" as const),
    kind,
    unit: options.unit ?? null,
    period_label: options.period ?? null,
    empty_values: [],
    missing_source_status: null,
  };
}

function observation(value: unknown, extra: Record<string, unknown> = {}) {
  return { field_key: "", value, status: "COLLECTED", observed_at: "2026-10-14T01:56:05Z", source_kind: "response", ...extra };
}

const PAYLOAD = {
  modules: {
    basic: {
      status: "COLLECTED",
      fields: [
        { ...observation("甄选聊车"), field_key: "nickname" },
        { ...observation("内蒙古自治区"), field_key: "province" },
        { ...observation("2"), field_key: "gender" },
        {
          ...observation({ kind: "number", bound: "exact", amount: "1351784" }, { unit: "count" }),
          field_key: "followers",
        },
        {
          ...observation(
            { kind: "number", bound: "exact", amount: "0.01969004266000137" },
            { unit: "ratio", period_label: "月" },
          ),
          field_key: "monthly_follower_growth_rate",
        },
      ],
    },
    fans: {
      status: "COLLECTED",
      fields: [
        {
          ...observation({
            kind: "structured",
            data: { 1: { value: 11860342, relative_ratio: -0.58 }, 2: { value: 6643390, relative_ratio: -0.57 }, 3: { value: 4930200, relative_ratio: -0.33 }, 4: { value: 5922, relative_ratio: 1.12 }, 5: { value: 23439854, relative_ratio: -0.54 } },
          }),
          field_key: "connection_funnel",
        },
        {
          ...observation({
            kind: "structured",
            data: { 1: { value: 11860342, same_industry_median: 466345 }, 2: { value: 6643390, same_industry_median: 96578 }, 3: { value: 4930200, same_industry_median: 20201 }, 4: { value: 5922, same_industry_median: 0 }, 5: { value: 23439854, rank_percent: 0.0125 } },
          }),
          field_key: "seeding_link_structure",
        },
        {
          ...observation({
            kind: "structured",
            // 粉丝总数窗口比连接用户窗口晚一天（真实平台行为），两条线在共享时间轴上各取各的点：
            // 09-14/10-12/10-13 有粉丝值，09-13/10-12 有连接用户值。
            data: [
              { date: "2026-09-14", fans_cnt: "1327473" },
              { date: "2026-10-12", fans_cnt: "1353611" },
              { date: "2026-10-13", fans_cnt: "1353611" },
            ],
          }),
          field_key: "fans_daily_trend",
        },
        {
          // 连接用户窗口口径；与粉丝总数窗口错开一天（真实平台行为），两条线在共享时间轴上各取各的点。
          ...observation({ kind: "structured", data: [{ date: "2026-09-13", value: 50275643 }, { date: "2026-10-12", value: 23439854 }] }),
          field_key: "connection_daily_trend",
        },
        {
          ...observation({ kind: "number", bound: "exact", amount: "23439854" }, { unit: "count", period_label: "月" }),
          field_key: "monthly_connected_users",
        },
      ],
    },
    spread: {
      status: "COLLECTED",
      fields: [
        // Label-only shape measured in 8 of 78 stored snapshots.
        { ...observation({ kind: "structured", data: { label: "影视娱乐" } }), field_key: "interaction_rate" },
        // CD-08: the two median leaves, live-verified for creator 6639192346380468227. The platform's
        // 「播放量中位数」 card is the nested one (766187 → 76.6w, 优于 99.23%); the top-level
        // `play_mid` (1399516) is rendered nowhere and must not be shown by the panel.
        {
          ...observation({
            kind: "structured",
            data: {
              item_num: { label: "", value: 5 },
              play_mid: { label: "", value: 766187, overtake: 9923 },
              interact_rate: {},
            },
          }),
          field_key: "item_rate_metrics",
        },
        { ...observation({ kind: "structured", data: "1399516" }), field_key: "play_median" },
        { ...observation({ kind: "structured", data: "19112" }), field_key: "average_duration" },
        { ...observation({ kind: "structured", data: "32600" }), field_key: "average_likes" },
        { ...observation({ kind: "structured", data: "1619" }), field_key: "average_comments" },
        { ...observation({ kind: "structured", data: "549" }), field_key: "average_shares" },
        {
          ...observation({ kind: "structured", data: { cpm_60: "2969", cpm_21_60: "2969" } }),
          field_key: "expected_cpm",
        },
      ],
    },
    commercial: {
      status: "COLLECTED",
      fields: [
        {
          ...observation({
            kind: "structured",
            data: [
              { desc: "植入视频", field: "long_video_price", price: 40000, origin_price: 50000, settlement_desc: "固定价格", is_open: true, start_time: "1787124536", end_time: "2145916800" },
            ],
          }),
          field_key: "cooperation_offers",
        },
      ],
    },
    fulfillment: {
      status: "COLLECTED",
      fields: [
        { ...observation("96"), field_key: "credit_score" },
        // Measured shape: a JSON document inside a string leaf.
        { ...observation({ kind: "structured", data: '[{"key":"1916","rate":"1.0","value":"6"}]' }), field_key: "industry_order_distribution" },
        { ...observation({ kind: "structured", data: '[{"key":"1916","rate":"0.5","value":"3"}]' }), field_key: "industry_play_distribution" },
        {
          ...observation({
            kind: "structured",
            data: [{ industry: { name: "汽车", rate: "0.8" }, first_category: [{ name: "出行", rate: "0.6" }], second_category: [] }],
          }),
          field_key: "cooperation_industry_distribution",
        },
      ],
    },
    creation: {
      status: "COLLECTED",
      fields: [
        {
          ...observation({
            kind: "structured",
            data: {
              interaction: { rate: 0.0191, compare_avg: -0.0338, compare_author: 0.25 },
              play_medium: { rate: 33847, compare_avg: 1.216375391010475, compare_author: 0.93 },
            },
          }),
          field_key: "performance_descriptions",
        },
        {
          // DATA-02 起，「创作能力 → 最新视频表现」改读独立存储的作品观测；快照里这份旧 JSONB 数据
          // **不再参与图表与列表**，但仍原样留在 payload 中（见下方测试：页面不得再展示它）。
          ...observation({
            kind: "structured",
            data: [
              {
                item_id: "jsonb-legacy-work",
                title: "JSONB 快照内的旧作品记录",
                play: 1,
                item_date: "2000-01-01",
                item_cover: "tos-cn-i-0813c000-ce/legacy",
                url: "https://example.com/legacy",
              },
            ],
          }),
          field_key: "recent_video_performance",
        },
      ],
    },
  },
  profile_complete: true,
  pipeline_complete: true,
};

const CREATOR: CreatorLibraryDetail = {
  creator_id: "33333333-3333-4333-8333-333333333333",
  platform: "douyin_xingtu",
  platform_creator_id: "7503176021160493065",
  display_name: "甄选聊车",
  avatar_uri: null,
  creator_type_label: "汽车",
  province: "内蒙古自治区",
  city: "赤峰市",
  industry_labels: ["金融业"],
  followers: metric("1351784"),
  monthly_deep_users: metric("11580000", true),
  monthly_connected_users: metric("23439854"),
  monthly_follower_growth_rate: metric("0.01969004266000137"),
  interaction_rate: metric(null),
  completion_rate: metric(null),
  expected_cpm_21_60: metric("2969"),
  expected_cpm_60_plus: metric("2969"),
  expected_cpe_21_60: metric("246"),
  expected_cpe_60_plus: metric("246"),
  play_median: metric(null),
  average_duration: metric(null),
  average_likes: metric(null),
  average_comments: metric(null),
  average_shares: metric(null),
  profile_complete: true,
  pipeline_complete: true,
  data_updated_at: "2026-10-14T01:56:05Z",
  latest_snapshot_id: "44444444-4444-4444-8444-444444444444",
  mcn_name: null,
  introduction: "关注我",
  gender: "2",
  content_theme_labels: ["用车知识"],
  collected_field_count: 79,
  failed_field_count: 0,
  field_sources: {},
  module_statuses: { basic: "COLLECTED", fans: "COLLECTED" },
  profile_payload: PAYLOAD,
};

/** 已入库的封面对象 id（STORED 的唯一合法来源）。 */
const COVER_OBJECT_ID = "cover/77777777-7777-4777-8777-777777777777/9f2c1d";

function videoRow(overrides: Partial<CreatorVideoObservation> = {}): CreatorVideoObservation {
  return {
    module_key: "recent_video_performance",
    position: 0,
    content_id: null,
    platform_item_id: null,
    platform_video_id: null,
    platform_author_id: "103411567572",
    title: null,
    subtitle: null,
    published_at: null,
    published_raw: null,
    play_count: null,
    like_count: null,
    comment_count: null,
    favorite_count: null,
    share_count: null,
    cover_source_uri: null,
    cover_object_id: null,
    cover_status: "NOT_PROVIDED",
    work_url: null,
    field_statuses: {},
    observed_at: "2026-10-16T01:43:32Z",
    ...overrides,
  };
}

/**
 * 作品观测接口的返回（DATA-02）：三条「最新视频」各覆盖一种封面状态
 * （STORED / UNRESOLVED / NOT_PROVIDED），另有一条「最新星图视频」用于核对集合切换。
 * `published_at` 为 null、只给平台原样 `published_raw`，是接口允许的形状之一。
 */
const VIDEO_PAGE: CreatorVideoPage = {
  creator_id: CREATOR.creator_id,
  snapshot_id: CREATOR.latest_snapshot_id,
  view_kind: "published",
  items: [
    videoRow({
      position: 0,
      platform_item_id: "7695691295523966970",
      content_id: "11111111-1111-4111-8111-111111111111",
      title: "雨刮器为什么不好用 #汽车知识",
      published_raw: "2026-10-12",
      // 数字字符串与 JSON 数字两种形状都要能展示。
      play_count: "915520",
      like_count: 12027,
      comment_count: 598,
      share_count: 36,
      cover_source_uri: "tos-cn-i-0813c000-ce/ownaEMiVAPe6AynMEABAIsZ6e81wlEDAAkipfP",
      cover_object_id: COVER_OBJECT_ID,
      cover_status: "STORED",
      work_url: "https://www.iesdouyin.com/share/video/7695691295523966970/?region=CN",
    }),
    videoRow({
      position: 1,
      platform_item_id: "7695317945446185338",
      title: "如何正确在应急车道停车",
      published_raw: "2026-10-11",
      play_count: 2719270,
      cover_source_uri: "tos-cn-i-0813c001/ab12cd34",
      cover_object_id: null,
      cover_status: "UNRESOLVED",
      work_url: "https://www.iesdouyin.com/share/video/7695317945446185338/?region=CN",
    }),
    videoRow({
      // 平台本次响应没有封面字段，也没有作品链接：不得提供可点击入口，也不得构造封面地址。
      position: 2,
      platform_item_id: "7694953511649698491",
      title: "高速上不能压的3种线",
      published_raw: "2026-10-10",
      play_count: "8840",
      cover_source_uri: null,
      cover_object_id: null,
      cover_status: "NOT_PROVIDED",
      work_url: null,
    }),
    videoRow({
      module_key: "recent_xingtu_video_performance",
      position: 0,
      platform_item_id: "7695000000000000001",
      title: "星图商单复盘",
      published_raw: "2026-10-09",
      play_count: "12345",
      cover_status: "NOT_PROVIDED",
      work_url: "https://www.iesdouyin.com/share/video/7695000000000000001/",
    }),
  ],
};

function metric(value: string | null, approximate = false) {
  return {
    value,
    raw_value: value,
    unit: value === null ? null : "count",
    is_approximate: approximate,
    status: value === null ? "NO_DATA" : "COLLECTED",
    observed_at: "2026-10-14T01:56:05Z",
  };
}

function renderProfile(
  catalog: unknown = CATALOG,
  creator: CreatorLibraryDetail = CREATOR,
  payload: Record<string, unknown> = PAYLOAD as Record<string, unknown>,
  videos: CreatorVideoPage | null = VIDEO_PAGE,
  videoState: { loading?: boolean; error?: unknown; onRetry?: () => void } = {},
  platform: "douyin_xingtu" | "kuaishou_juxing" = "douyin_xingtu",
) {
  vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === `/api/platforms/${platform}/profile-field-catalog`) {
      return Promise.resolve(
        new Response(JSON.stringify(catalog), { status: catalog ? 200 : 404, headers: { "Content-Type": "application/json" } }),
      );
    }
    return Promise.resolve(new Response("{}", { status: 404, headers: { "Content-Type": "application/json" } }));
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CreatorProfile
          creator={creator}
          payload={payload}
          platform={platform}
          backTo="/creators"
          backLabel="返回达人库"
          scopeLabel="当前达人资料"
          badgeLabel="采集完整"
          badgeTone="published"
          description="平台原始值"
          videos={videos}
          videosLoading={videoState.loading}
          videosError={videoState.error}
          onRetryVideos={videoState.onRetry}
          // 达人库入口的授权封面端点（按 creator_id 授权），与页面真实传参一致。
          videoCoverUrl={(objectId) =>
            `/api/creator-library/${creator.creator_id}/covers/${encodeURIComponent(objectId)}`
          }
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CreatorProfile", () => {
  it("merges the two daily series into one dual-axis chart and drops the removed 连接用户 modules", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "连接用户" }));

    // CD-06 需求二：两个趋势模块合并为一张图，左轴连接用户数 / 右轴粉丝数 / X 轴时间。
    const figure = document.querySelector(".chart-figure");
    expect(figure).not.toBeNull();
    expect(figure?.querySelectorAll("polyline.trend-line")).toHaveLength(2);
    expect(figure?.querySelector(".trend-line.tone-blue")).not.toBeNull();
    expect(figure?.querySelector(".trend-line.tone-crimson")).not.toBeNull();
    const axes = Array.from(document.querySelectorAll(".trend-axis-title")).map((n) => n.textContent);
    expect(axes).toEqual(["连接用户数", "粉丝数"]);
    const chartSvg = figure?.querySelector("svg");
    expect(chartSvg?.getAttribute("aria-label") ?? "").toContain("双轴");

    // 轴标签按「万」展示（本项目既有单位规则）。
    const ticks = Array.from(document.querySelectorAll(".trend-tick")).map((n) => n.textContent);
    expect(ticks.some((text) => (text ?? "").endsWith("万"))).toBe(true);

    // 两个已被移除的模块不再出现。
    expect(screen.queryByText("连接用户规模与粉丝增长")).not.toBeInTheDocument();
    expect(screen.queryByText("近 30 日粉丝日增量")).not.toBeInTheDocument();
    expect(document.querySelector(".delta-bar")).toBeNull();
    // 平台口径说明随合并后的标题保留。
    expect(view.getByText("近 30 日连接用户与粉丝趋势")).toBeInTheDocument();
    expect(view.getByText(/不可求和/)).toBeInTheDocument();
  });

  it("shows both quantities when a date is hovered in the merged 连接用户 chart", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "连接用户" }));

    expect(document.querySelector(".trend-tip")).toBeNull();
    const capture = document.querySelector(".trend-capture");
    expect(capture).not.toBeNull();
    // jsdom 不做真实布局，因此直接派发 mousemove（真实鼠标交互由真实浏览器验收覆盖）。
    fireEvent.mouseMove(capture as Element, { clientX: 360, clientY: 120 });
    const tip = document.querySelector(".trend-tip");
    expect(tip).not.toBeNull();
    expect(tip?.getAttribute("role")).toBe("tooltip");
    // 浮层同时给出两个口径的名称与数值（粉丝总数窗口与连接用户窗口错开一天，此处取两者都有值的日期）。
    expect(tip?.textContent).toContain("连接用户数");
    expect(tip?.textContent).toContain("粉丝数");
    expect(tip?.textContent).toContain("23,439,854");
    expect(tip?.textContent).toContain("1,353,611");
    // 移出后浮层关闭。
    fireEvent.mouseLeave(capture as Element);
    expect(document.querySelector(".trend-tip")).toBeNull();
  });

  it("labels fields from the registry catalog and marks an evidence-corrected name", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "履约能力" }));
    // Observed labels come from the catalog, not from a hardcoded or English map.
    expect(await view.findByText("信用分")).toBeInTheDocument();
    expect(view.queryByText("credit_score")).not.toBeInTheDocument();
  });

  it("shows the CD-06 履约能力 chapter with only 履约与合作表现", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "履约能力" }));
    const headings = Array.from(document.querySelectorAll(".chapter-body .profile-heading h3")).map((n) => n.textContent);
    expect(headings).toEqual(["履约与合作表现"]);
    for (const removed of ["行业订单分布", "行业播放分布", "合作行业分布"]) {
      expect(screen.queryByText(removed)).not.toBeInTheDocument();
    }
    // 数据本身未被删除：字段仍在 payload 中，仍可在字段来源抽屉查看。
    expect(JSON.stringify(PAYLOAD)).toContain("industry_order_distribution");
    expect(JSON.stringify(PAYLOAD)).toContain("cooperation_industry_distribution");
  });

  it("shows the CD-03 identity rail: 星图ID, reordered metrics, 万/k units, 性别, 介绍", async () => {
    const view = renderProfile();
    // 需求 4.2 — the platform id under the nickname, not the internal UUID.
    const starId = view.getByTitle("复制星图ID 7503176021160493065");
    expect(starId).toHaveTextContent("星图ID");
    expect(starId).toHaveTextContent("7503176021160493065");
    expect(document.querySelector(".identity-rail")?.textContent).not.toContain(
      "33333333-3333-4333-8333-333333333333",
    );
    // 需求 4.3 — 月连接用户 → 月深度用户 → 粉丝 → 月涨粉率.
    expect(Array.from(document.querySelectorAll(".rail-kpis span")).map((node) => node.textContent)).toEqual([
      "月连接用户",
      "月深度用户",
      "粉丝",
      "月涨粉率",
    ]);
    // 需求 4.4 — 23,439,854 → 2,344.0万; 1,351,784 → 135.2万; the approximate figure keeps ≈.
    expect(view.getByText("2,344.0万")).toBeInTheDocument();
    expect(view.getByText("≈1,158.0万")).toBeInTheDocument();
    expect(view.getByText("135.2万")).toBeInTheDocument();
    expect(view.getByText("1.97%")).toBeInTheDocument();
    // 需求 4.5 — 内容主题 before 行业标签.
    expect(Array.from(document.querySelectorAll(".rail-tags dt")).map((node) => node.textContent)).toEqual([
      "达人类型",
      "内容主题",
      "行业标签",
    ]);
    // 需求 4.6 — the stored code 2 maps to 女 and keeps the code in the note; 4.11 — 介绍 is shown.
    const railGender = document.querySelector(".rail-gender");
    expect(railGender?.textContent).toBe("女");
    expect(railGender).toHaveAttribute("title", "平台编码 2（2026-10-14 线上确证）");
    expect(document.querySelector(".rail-introduction")?.textContent).toBe("关注我");
    // 需求 4.1/4.7/4.8/4.10 — the removed labels and the 数据来源 entry are gone.
    expect(Array.from(document.querySelectorAll(".rail-facts dt")).map((node) => node.textContent)).toEqual([
      "性别",
      "地区",
      "MCN",
      "介绍",
    ]);
    expect(view.queryByRole("button", { name: /数据来源/ })).not.toBeInTheDocument();
    expect(document.querySelector(".identity-rail")?.textContent).not.toMatch(
      /采集完整|数据不完整|观测|完整性|商业与表现指标均为平台原始值/,
    );
  });

  it("keeps a multi-line 介绍 intact and falls back to the platform empty state", () => {
    // 需求 4.11 — the platform's own line breaks survive verbatim (CSS pre-wrap owns the wrapping).
    const multiLine = "商务合作：kuofafafa\n有经验剪辑合作：sence99";
    // Gender is deliberately removed from the payload: the rail must show the platform empty state.
    const fields = PAYLOAD.modules.basic.fields.filter((entry) => entry.field_key !== "gender");
    const payload = {
      ...PAYLOAD,
      modules: {
        ...PAYLOAD.modules,
        basic: {
          status: "COLLECTED",
          fields: [...fields, { ...observation(multiLine), field_key: "introduction" }],
        },
      },
    };
    const view = renderProfile(undefined, { ...CREATOR, introduction: multiLine, gender: null }, payload);
    expect(document.querySelector(".rail-introduction span")?.textContent).toBe(multiLine);
    expect(document.querySelector(".rail-introduction span")?.textContent).toContain("\n");
    // A missing gender is the platform's own empty state, never a guessed label or the text "null".
    const genderDatum = Array.from(document.querySelectorAll(".rail-facts > div")).find(
      (node) => node.querySelector("dt")?.textContent === "性别",
    );
    expect(genderDatum?.textContent).toContain("平台暂无数据");
    expect(document.querySelector(".identity-rail")?.textContent).not.toContain("null");
    void view;
  });

  it("renders the connected-user layers as a partition with an explicit total", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "连接用户" }));
    const stack = await view.findByRole("img", { name: "连接用户分层结构" });
    // Layer names and the total label come from the live platform page.
    expect(stack.textContent).toContain("了解");
    expect(stack.textContent).toContain("兴趣");
    expect(stack.textContent).toContain("喜欢");
    expect(stack.textContent).toContain("追随");
    expect(stack.textContent).toContain("连接用户数（合计）");
    // 11,860,342 + 6,643,390 + 4,930,200 + 5,922 === 23,439,854
    expect(stack.textContent).toContain("各层合计 23,439,854，与合计值一致");
    expect(stack.textContent).toContain("同行业中位 466,345");
    // A funnel chart would need nested stages; the platform's numbers are a partition.
    expect(stack.textContent).not.toContain("漏斗");
  });

  it("shows the platform's 播放量中位数 from item_rate_metrics, never the top-level play_mid", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "商业能力" }));
    expect(await screen.findByText("内容数据")).toBeInTheDocument();
    const tile = Array.from(document.querySelectorAll(".biz-metric")).find(
      (node) => node.querySelector(".biz-metric-label")?.textContent === "播放量中位数",
    );
    expect(tile).toBeTruthy();
    // 766187 → 76.6w（平台线上同值）；1399516（顶层 play_mid）必须不出现。
    expect(tile?.querySelector("strong")?.textContent).toBe("76.6w");
    expect(tile?.querySelector(".biz-compare")?.textContent).toBe("优于 99.2% 同类型达人");
    expect(tile?.querySelector(".biz-original")?.textContent).toBe("平台原值 766187 / 超越原值 9923");
    expect(view.container.textContent).not.toContain("139.9w");
    expect(view.container.textContent).not.toContain("1399516");

    // 「转化价值」里另有一张「视频播放中位数」（conversion.related_video_play_median）。它来自
    // 另一个字段；本 fixture 未采集该字段，因此必须如实降级，不得借用上面的中位播放量。
    const conversionTile = Array.from(document.querySelectorAll(".biz-metric")).find(
      (node) => node.querySelector(".biz-metric-label")?.textContent === "视频播放中位数",
    );
    expect(conversionTile?.querySelector("strong")?.textContent).toBe("—");
  });

  it("turns a label-only rate response into an explicit state instead of a number", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "商业能力" }));
    // CD-04: 商业能力 renders the four business modules; a label-only rate keeps its platform state
    // instead of becoming a number.
    expect(await screen.findByText("内容数据")).toBeInTheDocument();
    const interaction = Array.from(document.querySelectorAll(".biz-metric")).find((node) =>
      node.textContent?.startsWith("互动率"),
    );
    expect(interaction?.textContent).toContain("影视娱乐");
    expect(interaction?.textContent).not.toMatch(/\d+(\.\d+)?%/);
  });

  it("renders the four business modules of the CD-04 commercial chapter without 报价明细/历史合作行业", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "商业能力" }));
    expect(await screen.findByText("内容数据")).toBeInTheDocument();
    // 历史合作行业 与 报价明细 已按要求从本章节移除（见 CD-04 状态历史 2026-10-15 第三次调整）。
    for (const title of ["内容数据", "性价比/效果预估", "种草价值", "转化价值"]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
    const headings = Array.from(document.querySelectorAll(".profile-heading h3")).map((n) => n.textContent);
    expect(headings).toEqual(["内容数据", "性价比/效果预估", "种草价值", "转化价值"]);
    for (const removed of ["历史合作行业", "报价明细"]) {
      expect(screen.queryByRole("heading", { name: removed })).not.toBeInTheDocument();
    }
  });

  it("removes the 「视频表现口径对照」 module without touching its data", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));
    // CD-05 任务四：模块标题、对照表容器与表体都不再出现在页面上。
    expect(screen.queryByText("视频表现口径对照")).not.toBeInTheDocument();
    expect(document.querySelector(".compare-table")).toBeNull();
    expect(document.querySelector(".chapter-body")?.textContent).not.toContain("compare_avg");
    // 但「最新视频表现」本身不受影响，且原字段仍留在 payload 中（未删数据）。
    expect(screen.getByText("最新视频表现")).toBeInTheDocument();
    expect(JSON.stringify(PAYLOAD)).toContain("performance_descriptions");
  });

  it("shows each video's real play count on its bar by default, with the publish date on the x axis", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));

    // 默认可见的播放量标签：不需要 Hover。单位遵循 CD-03 已确认规则（≥1万→万，1千–1万→k，<1千原数）。
    const labels = Array.from(document.querySelectorAll(".video-bar-value")).map((n) => n.textContent);
    expect(labels).toEqual(["91.6万", "271.9万", "8.8k"]);

    // X 轴改为真实发布时间，不再是 1、2、3 序号。
    const dates = Array.from(document.querySelectorAll(".video-bar-date")).map((n) => n.textContent);
    expect(dates).toEqual(["2026-10-12", "2026-10-11", "2026-10-10"]);
    expect(document.querySelector(".video-bars")?.textContent).not.toMatch(/^123$/);

    // 柱高仍由真实播放量决定：最大播放量的柱子最高。
    const heights = Array.from(document.querySelectorAll(".video-bar i")).map((n) =>
      Number.parseFloat((n as HTMLElement).style.height),
    );
    expect(heights[1]).toBe(100);
    expect(heights[0]).toBeGreaterThan(0);
    expect(heights[0]).toBeLessThan(100);

    // DATA-02：图表与列表只读作品观测接口，快照 JSONB 里的旧视频数据不再参与展示（数据本身仍在 payload 中）。
    expect(document.querySelector("#content")?.textContent).not.toContain("JSONB 快照内的旧作品记录");
    expect(JSON.stringify(PAYLOAD)).toContain("JSONB 快照内的旧作品记录");
  });

  it("switches 最新视频 / 最新星图视频 from the same observation page", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));
    expect(document.querySelectorAll(".video-bar-slot")).toHaveLength(3);

    await user.click(view.getByRole("button", { name: "最新星图视频" }));
    // 只切换当前集合：另一集合的作品不得混入（图表与列表仍是同一份数组）。
    expect(Array.from(document.querySelectorAll(".video-bar-value")).map((n) => n.textContent)).toEqual([
      "1.2万",
    ]);
    const barLinks = Array.from(document.querySelectorAll("a.video-bar")).map((n) => n.getAttribute("href"));
    const cardLinks = Array.from(document.querySelectorAll("a.video-card")).map((n) => n.getAttribute("href"));
    expect(cardLinks).toEqual(barLinks);
    expect(document.querySelectorAll(".video-bar-slot")).toHaveLength(1);
    expect(document.querySelector("#content")?.textContent).not.toContain("雨刮器为什么不好用");

    await user.click(view.getByRole("button", { name: "最新视频" }));
    expect(document.querySelectorAll(".video-bar-slot")).toHaveLength(3);
  });

  it("links the bar and the work card to that video's real work url", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));

    const barLinks = Array.from(document.querySelectorAll("a.video-bar")).map((n) => n.getAttribute("href"));
    expect(barLinks).toEqual([
      "https://www.iesdouyin.com/share/video/7695691295523966970/?region=CN",
      "https://www.iesdouyin.com/share/video/7695317945446185338/?region=CN",
    ]);
    // 每条链接都带有 target=_blank，外部跳转保留当前详情页。
    for (const link of Array.from(document.querySelectorAll("a.video-bar"))) {
      expect(link.getAttribute("target")).toBe("_blank");
    }
    // 图表与下方作品卡片使用同一批规范化数据（CRE-19）。
    const cardLinks = Array.from(document.querySelectorAll("a.video-card")).map((n) => n.getAttribute("href"));
    expect(cardLinks).toEqual(barLinks);
    // 缺 url 的作品不提供可点击入口，也不猜测地址。
    expect(document.querySelectorAll(".video-card.no-link")).toHaveLength(1);
    expect(document.querySelectorAll(".video-bar-slot")).toHaveLength(3);
  });

  it("renders each work card's cover according to its own status, never substituting another work's cover", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));

    const cards = Array.from(document.querySelectorAll(".video-card"));
    expect(cards).toHaveLength(3);
    expect(cards[0].textContent).toContain("雨刮器为什么不好用");
    expect(cards[0].textContent).toContain("915,520");
    expect(cards[0].textContent).toContain("2026-10-12");

    // 只有 STORED 的作品渲染 <img>，且 src 来自该入口的授权封面端点（按 creator_id 授权），不是平台 CDN。
    const stored = cards[0].querySelector(".video-card-cover img");
    expect(document.querySelectorAll(".video-card-cover img")).toHaveLength(1);
    expect(stored?.getAttribute("src")).toBe(
      `/api/creator-library/${CREATOR.creator_id}/covers/${encodeURIComponent(COVER_OBJECT_ID)}`,
    );

    // UNRESOLVED（有平台 key、未入库）与 NOT_PROVIDED（平台没给封面字段）各自一句占位文案与解释，不共用同一句。
    const placeholders = Array.from(document.querySelectorAll(".video-card-cover-empty"));
    expect(placeholders).toHaveLength(2);
    const unresolved = placeholders[0].querySelector("span");
    expect(unresolved?.textContent).toBe("封面未生成");
    expect(unresolved?.getAttribute("title")).toContain("还没有存成");
    const notProvided = placeholders[1].querySelector("span");
    expect(notProvided?.textContent).toBe("平台未返回封面");
    expect(notProvided?.getAttribute("title")).toContain("没有该作品的封面字段");
  });

  it("keeps the existing 封面加载失败 degrade when a stored cover cannot be loaded", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));

    const img = document.querySelector(".video-card-cover img");
    expect(img).not.toBeNull();
    fireEvent.error(img as Element);
    const placeholder = document.querySelector(".video-card-cover-empty");
    expect(placeholder?.querySelector("span")?.textContent).toBe("封面加载失败");
    // 失败态不回落到其它作品的封面。
    expect(document.querySelectorAll(".video-card-cover img")).toHaveLength(0);
  });

  it("shows the loading note while the work observations are still being read", async () => {
    const view = renderProfile(undefined, undefined, undefined, null, { loading: true });
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));
    expect(document.querySelector("#content .profile-empty")?.textContent).toBe("正在读取作品观测…");
    expect(document.querySelector(".video-bars")).toBeNull();
    expect(document.querySelector("#content .profile-heading > span")?.textContent).toBe("读取中");
  });

  it("shows the error note with a working retry button when the work observations fail", async () => {
    const retry = vi.fn();
    const view = renderProfile(undefined, undefined, undefined, null, {
      error: new Error("观测接口不可用"),
      onRetry: retry,
    });
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));
    const error = document.querySelector("#content .biz-error");
    expect(error).not.toBeNull();
    expect(error?.textContent).toContain("观测接口不可用");
    expect(document.querySelector("#content .profile-heading > span")?.textContent).toBe("读取失败");
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(retry).toHaveBeenCalledTimes(1);
    // 读取失败时不渲染图表或作品卡片，也不抛错。
    expect(document.querySelector(".video-bars")).toBeNull();
    expect(document.querySelectorAll(".video-card")).toHaveLength(0);
  });

  it("shows the video title and play count in a hover layer on the bar", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));

    expect(document.querySelector(".video-tip")).toBeNull();
    await user.hover(document.querySelectorAll(".video-bar")[0]);
    const tip = document.querySelector(".video-tip");
    expect(tip).not.toBeNull();
    expect(tip?.textContent).toContain("雨刮器为什么不好用");
    expect(tip?.textContent).toContain("播放量");
    expect(tip?.textContent).toContain("915,520");
    expect(tip?.textContent).toContain("2026-10-12");
    expect(tip?.getAttribute("role")).toBe("tooltip");
    // 浮层封面同样按状态渲染：第一条是 STORED，因此浮层里是授权端点的 <img>。
    expect(tip?.querySelector(".video-tip-cover img")?.getAttribute("src")).toBe(
      `/api/creator-library/${CREATOR.creator_id}/covers/${encodeURIComponent(COVER_OBJECT_ID)}`,
    );
  });

  it("renders an empty state instead of a broken chart when there are no video records", async () => {
    const view = renderProfile(CATALOG, CREATOR, PAYLOAD as Record<string, unknown>, null);
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));
    // 空数据不渲染图表、柱子或作品卡片，也不抛错；空态使用本次观测量为空时的固定文案。
    expect(document.querySelector(".video-bars")).toBeNull();
    expect(document.querySelectorAll(".video-bar-slot")).toHaveLength(0);
    expect(document.querySelectorAll(".video-card")).toHaveLength(0);
    expect(document.querySelector(".video-tip")).toBeNull();
    const empty = document.querySelector("#content .profile-empty");
    expect(empty).not.toBeNull();
    expect(empty?.textContent).toBe("本次没有视频记录。");
    expect(document.querySelector("#content .profile-heading > span")?.textContent).toBe("平台未返回作品记录");
    // 「视频表现口径对照」在空数据下同样不存在。
    expect(screen.queryByText("视频表现口径对照")).not.toBeInTheDocument();
  });

  it("falls back to the default 商业能力 chapter when the legacy 达人概览 anchor is in the url", async () => {
    // 旧标识（#overview 是 CD-02/03/04 概览面板的 id）不得产生空白页。
    window.history.replaceState(null, "", "#overview");
    const view = renderProfile();
    expect(document.querySelector(".chapter-tabs button.active")?.textContent).toBe("商业能力");
    expect(view.queryByRole("tab", { name: "达人概览" })).not.toBeInTheDocument();
    expect(document.querySelector(".chapter-body")?.textContent?.length).toBeGreaterThan(0);
    window.history.replaceState(null, "", "#");
  });

  it("returns to the default chapter when a legacy anchor arrives as a same-document hash change", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    // 页内跳转（同一文档改 hash）不会重新挂载组件，因此必须监听 hashchange。
    await user.click(view.getByRole("tab", { name: "履约能力" }));
    expect(document.querySelector(".chapter-tabs button.active")?.textContent).toBe("履约能力");
    window.history.replaceState(null, "", "#overview");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(await view.findByRole("tab", { name: "商业能力", selected: true })).toBeInTheDocument();
    expect(document.querySelector(".chapter-tabs button.active")?.textContent).toBe("商业能力");
    window.history.replaceState(null, "", "#");
  });

  it("keeps a JSON-string distribution leaf out of the page after CD-06 removes the 履约能力 distributions", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "履约能力" }));
    // 该字段仍是 JSON 字符串叶子，但本轮已移除其展示模块；页面不得泄漏原始 JSON。
    expect(screen.queryByText("行业 1916")).not.toBeInTheDocument();
    expect(document.querySelector(".chapter-body")?.textContent).not.toContain('"rate"');
    // 履约与合作表现仍正常渲染平台真实值。
    expect(view.getByText("履约与合作表现")).toBeInTheDocument();
    expect(view.getByText("96")).toBeInTheDocument();
  });

  it("falls back to the platform field key when the catalog is unavailable", async () => {
    const view = renderProfile(null);
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "履约能力" }));
    // Without the catalog the raw field key is shown, and no invented Chinese name is used.
    expect(await view.findByText("credit_score")).toBeInTheDocument();
    expect(screen.queryByText("信用分")).not.toBeInTheDocument();
  });

const JUXING_CATALOG: ProfileFieldCatalog = {
  platform: "kuaishou_juxing",
  contract_version: "juxing-test",
  modules: [
    {
      key: "basic",
      fields: [
        field("platform_creator_id", "快手达人 ID", "text"),
        field("nickname", "昵称", "text"),
        field("avatar_uri", "头像", "text"),
        field("province", "省份", "text"),
        field("city", "城市", "text"),
        field("content_type_labels", "内容类型", "tags"),
        field("gender", "性别", "text"),
        field("profile_url", "主页地址", "text"),
        field("content_form_labels", "内容形式", "tags"),
        field("mcn_name", "MCN", "text"),
        field("introduction", "介绍", "text"),
        field("followers", "粉丝数", "number", { unit: "count" }),
        field("monthly_follower_growth_count", "近30天涨粉", "number", { unit: "count" }),
        field("monthly_follower_growth_rate", "月涨粉率", "ratio", { unit: "ratio" }),
        field("cooperation_offers", "视频报价", "structured"),
      ],
    },
    {
      key: "spread",
      fields: [
        field("play_median", "播放量中位数", "number", { unit: "count" }),
        field("expected_cpm", "预期 CPM", "number", { unit: "CNY_per_thousand_impressions" }),
        field("interaction_rate", "互动率", "ratio", { unit: "ratio" }),
        field("video_count", "视频数", "number", { unit: "count" }),
      ],
    },
    { key: "works", fields: [field("works", "代表及近期作品", "structured")] },
    {
      key: "audience",
      fields: [
        field("fan_portrait", "粉丝画像", "structured"),
        field("viewer_portrait", "观众画像", "structured"),
      ],
    },
  ],
};

const JUXING_PAYLOAD = {
  modules: {
    basic: {
      status: "COLLECTED",
      fields: [
        { ...observation("578000000001"), field_key: "platform_creator_id" },
        { ...observation("合成聚星达人"), field_key: "nickname" },
        { ...observation("广东省"), field_key: "province" },
        { ...observation("深圳市"), field_key: "city" },
        { ...observation(["母婴亲子"]), field_key: "content_type_labels" },
        { ...observation("女"), field_key: "gender" },
        { ...observation("www.kuaishou.com/profile/example"), field_key: "profile_url" },
        { ...observation(["推荐"]), field_key: "content_form_labels" },
        { ...observation("合成 MCN"), field_key: "mcn_name" },
        { ...observation("合成简介"), field_key: "introduction" },
        {
          ...observation({ kind: "number", bound: "exact", amount: "21686076" }, { unit: "count" }),
          field_key: "followers",
        },
        {
          ...observation({ kind: "number", bound: "exact", amount: "268703" }, { unit: "count", period_label: "近30天" }),
          field_key: "monthly_follower_growth_count",
        },
        {
          ...observation({ kind: "number", bound: "exact", amount: "0.0125" }, { unit: "ratio", period_label: "近30天" }),
          field_key: "monthly_follower_growth_rate",
        },
        {
          ...observation(
            {
              kind: "structured",
              data: [
                { duration: "1-20秒", platform_price_raw: 20000, price_yuan: 20, currency: "CNY" },
              ],
            },
            { period_label: "页面报价" },
          ),
          field_key: "cooperation_offers",
        },
      ],
    },
    spread: {
      status: "COLLECTED",
      fields: [
        {
          ...observation({ kind: "number", bound: "exact", amount: "13092269" }, { unit: "count", period_label: "近30天/流量范围7天" }),
          field_key: "play_median",
        },
        {
          ...observation({ kind: "number", bound: "exact", amount: "20" }, { unit: "CNY_per_thousand_impressions", period_label: "近30天/流量范围7天" }),
          field_key: "expected_cpm",
        },
        {
          ...observation({ kind: "number", bound: "exact", amount: "0.03911" }, { unit: "ratio", period_label: "近30天/流量范围7天" }),
          field_key: "interaction_rate",
        },
        {
          ...observation({ kind: "number", bound: "exact", amount: "15" }, { unit: "count", period_label: "近30天/流量范围7天" }),
          field_key: "video_count",
        },
      ],
    },
    works: {
      status: "COLLECTED",
      fields: [
        {
          ...observation({
            kind: "structured",
            data: [
              {
                platform_content_id: "synthetic-work-1",
                title: "合成作品",
                play_count: 100,
                like_count: 10,
                comment_count: 2,
                share_count: 1,
                published_at_ms: 1760000000000,
                cover_url: "https://p3-ad.adukwai.com/example-cover.jpg",
                product_name: "合成商品",
                quality_hot: true,
                contains_paid: false,
                first_industry_name: "未知",
              },
            ],
          }),
          field_key: "works",
        },
      ],
    },
    audience: {
      status: "COLLECTED",
      fields: [
        {
          ...observation(
            {
              kind: "structured",
              data: {
                sexPercentage: [{ label: "女性", value: 0.97, tgi: 224 }, { label: "男性", value: 0.03, tgi: 5 }],
                agePercentage: [{ label: "31-40", value: 0.24, tgi: 120 }, { label: "24-30", value: 0.3, tgi: 110 }],
                areaPercentage: [{ label: "山东", value: 0.13, tgi: 183 }, { label: "河北", value: 0.12, tgi: 160 }],
                interestPercentage: [],
              },
            },
            { period_label: "近30天" },
          ),
          field_key: "fan_portrait",
        },
        {
          ...observation({ kind: "structured", data: { sexPercentage: [{ label: "女性", value: 0.5, tgi: 100 }] } }, { period_label: "近30天" }),
          field_key: "viewer_portrait",
        },
      ],
    },
  },
  profile_complete: true,
  pipeline_complete: true,
};

const JUXING_CREATOR: CreatorLibraryDetail = {
  creator_id: "55555555-5555-4555-8555-555555555555",
  platform: "kuaishou_juxing",
  platform_creator_id: "578000000001",
  display_name: "合成聚星达人",
  avatar_uri: null,
  creator_type_label: null,
  province: "广东省",
  city: "深圳市",
  industry_labels: [],
  content_theme_labels: ["母婴亲子"],
  followers: metric("21686076"),
  monthly_deep_users: metric(null),
  monthly_connected_users: metric(null),
  monthly_follower_growth_rate: metric("0.0125"),
  interaction_rate: metric(null),
  completion_rate: metric(null),
  expected_cpm_21_60: metric(null),
  expected_cpm_60_plus: metric(null),
  expected_cpe_21_60: metric(null),
  expected_cpe_60_plus: metric(null),
  play_median: metric("186"),
  average_duration: metric("10.476"),
  average_likes: metric("2"),
  average_comments: metric(null),
  average_shares: metric(null),
  profile_complete: true,
  pipeline_complete: true,
  data_updated_at: "2026-10-27T20:00:00+08:00",
  latest_snapshot_id: "66666666-6666-4666-8666-666666666666",
  mcn_name: "合成 MCN",
  introduction: "合成简介",
  gender: null,
  collected_field_count: 19,
  failed_field_count: 0,
  field_sources: {},
  module_statuses: { basic: "COLLECTED", spread: "COLLECTED", works: "COLLECTED", audience: "COLLECTED" },
  profile_payload: JUXING_PAYLOAD,
};

describe("CreatorProfile (juxing)", () => {
  it("renders juxing chapters, platform-native units and a 快手ID without Xingtu semantics", async () => {
    const view = renderProfile(
      JUXING_CATALOG,
      JUXING_CREATOR,
      JUXING_PAYLOAD as Record<string, unknown>,
      null,
      {},
      "kuaishou_juxing",
    );
    const user = userEvent.setup();
    // The rail identifies the platform's own id and only shows juxing KPIs.
    expect(await view.findByText("快手ID")).toBeInTheDocument();
    expect(view.queryByText("星图ID")).not.toBeInTheDocument();
    expect(view.getByText("性别")).toBeInTheDocument();
    expect(view.getByText("女")).toBeInTheDocument();
    expect(view.getByText("内容形式")).toBeInTheDocument();
    expect(view.getByText("推荐")).toBeInTheDocument();
    expect(view.getByRole("link", { name: /打开主页/ })).toHaveAttribute("href", "https://www.kuaishou.com/profile/example");
    expect(view.getByText("粉丝")).toBeInTheDocument();
    expect(view.getByText("近30天涨粉")).toBeInTheDocument();
    expect(view.getByText("月涨粉率")).toBeInTheDocument();
    expect(view.getByText("作品数")).toBeInTheDocument();
    // Xingtu-only chapters must not exist.
    expect(view.queryByRole("tab", { name: "商业能力" })).not.toBeInTheDocument();
    expect(view.queryByRole("tab", { name: "创作能力" })).not.toBeInTheDocument();
    expect(view.queryByRole("tab", { name: "履约能力" })).not.toBeInTheDocument();
    expect(view.getByRole("tab", { name: "基础资料" })).toHaveAttribute("aria-selected", "true");

    // Default chapter: content type and the platform offer rows (raw integer and CNY value).
    expect(view.getAllByText("母婴亲子").length).toBeGreaterThan(0);
    expect(await view.findByText("1-20秒")).toBeInTheDocument();
    expect(view.getByText("20 元")).toBeInTheDocument();
    expect(view.getByText("平台原值 20,000")).toBeInTheDocument();

    await user.click(view.getByRole("tab", { name: "传播表现" }));
    expect(await view.findByText("播放量中位数")).toBeInTheDocument();
    expect(view.getByText("13,092,269")).toBeInTheDocument();
    expect(view.getByText("预期 CPM")).toBeInTheDocument();
    // The field's own observation window is kept; the catalog registers no period for juxing.
    expect(view.getAllByText(/近30天\/流量范围7天/).length).toBeGreaterThan(0);

    await user.click(view.getByRole("tab", { name: "代表作品" }));
    expect(await view.findByText("合成作品")).toBeInTheDocument();
    expect(view.getByText("100")).toBeInTheDocument();
    // The platform's 作品波动 card is the first-15 mean; the page reproduces that calculation
    // separately from the statistics-interface average fields.
    expect(view.getByText("作品波动（最近15个作品平均）")).toBeInTheDocument();
    expect(view.getByText("播放 100 · 点赞 10 · 评论 2 · 分享 1")).toBeInTheDocument();

    await user.click(view.getByRole("tab", { name: "受众画像" }));
    expect(await view.findByText("粉丝画像")).toBeInTheDocument();
    expect(view.getByText("观众画像")).toBeInTheDocument();
    expect(view.getAllByText("查看平台原始结构").length).toBe(2);
  });

  it("renders juxing covers, verified work badges and parsed portrait distributions", async () => {
    const view = renderProfile(
      JUXING_CATALOG,
      JUXING_CREATOR,
      JUXING_PAYLOAD as Record<string, unknown>,
      null,
      {},
      "kuaishou_juxing",
    );
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "代表作品" }));
    const cover = view.container.querySelector(".juxing-work img");
    expect(cover).not.toBeNull();
    expect(cover).toHaveAttribute("src", "https://p3-ad.adukwai.com/example-cover.jpg");
    expect(await view.findByText(/带货商品：合成商品/)).toBeInTheDocument();
    expect(view.getByText("优质")).toBeInTheDocument();
    await user.click(view.getByRole("tab", { name: "受众画像" }));
    expect(await view.findByText("97.0%")).toBeInTheDocument();
    expect(view.getByText("224")).toBeInTheDocument();
    expect(view.getAllByText("性别").length).toBeGreaterThan(1);
    expect(view.getByText("24-30")).toBeInTheDocument();
    expect(view.getByText("山东")).toBeInTheDocument();
  });

  it("never shows a Xingtu metric as zero for a missing juxing dimension", () => {
    const view = renderProfile(
      JUXING_CATALOG,
      JUXING_CREATOR,
      JUXING_PAYLOAD as Record<string, unknown>,
      null,
      {},
      "kuaishou_juxing",
    );
    // 月连接用户/月深度用户/CPM/CPE 不属于聚星合同：不出现 0，也不出现这些星图标签。
    expect(view.queryByText("月深度用户")).not.toBeInTheDocument();
    expect(view.queryByText("月连接用户")).not.toBeInTheDocument();
    expect(view.queryByText("CPM / CPE 原始值")).not.toBeInTheDocument();
  });
});

});
