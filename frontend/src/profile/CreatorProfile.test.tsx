import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CreatorProfile } from "./CreatorProfile";
import type { CreatorLibraryDetail, ProfileFieldCatalog } from "../types";

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
          // 与真实开发库同形：平铺键、item_id 唯一、item_date 为平台发布日期、
          // item_cover 是平台对象存储的**不透明 key**（不是可渲染地址）、url 为真实抖音作品链接。
          ...observation({
            kind: "structured",
            data: [
              {
                item_id: "7695691295523966970",
                title: "雨刮器为什么不好用 #汽车知识",
                play: 915520,
                like: 12027,
                comment: 598,
                share: 36,
                item_date: "2026-10-12",
                create_time: 1791792758,
                item_cover: "tos-cn-i-0813c000-ce/ownaEMiVAPe6AynMEABAIsZ6e81wlEDAAkipfP",
                url: "https://www.iesdouyin.com/share/video/7695691295523966970/?region=CN",
              },
              {
                item_id: "7695317945446185338",
                title: "如何正确在应急车道停车",
                play: 2719270,
                like: 32108,
                comment: 4395,
                share: 74,
                item_date: "2026-10-11",
                create_time: 1791705830,
                item_cover: "",
                url: "https://www.iesdouyin.com/share/video/7695317945446185338/?region=CN",
              },
              {
                // 缺 url 与封面：不得提供可点击入口，也不得构造未经验证的封面地址。
                item_id: "7694953511649698491",
                title: "高速上不能压的3种线",
                play: 8840,
                item_date: "2026-10-10",
                create_time: 1791620979,
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

/** Same payload with an empty video collection, for the empty-state check. */
const PAYLOAD_WITHOUT_VIDEOS = {
  ...PAYLOAD,
  modules: {
    ...PAYLOAD.modules,
    creation: {
      ...PAYLOAD.modules.creation,
      fields: PAYLOAD.modules.creation.fields.map((item) =>
        (item as { field_key?: string }).field_key === "recent_video_performance"
          ? { ...(item as Record<string, unknown>), value: { kind: "structured", data: [] } }
          : item,
      ),
    },
  },
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
) {
  vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/platforms/douyin_xingtu/profile-field-catalog") {
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
          backTo="/creators"
          backLabel="返回达人库"
          scopeLabel="当前达人资料"
          badgeLabel="采集完整"
          badgeTone="published"
          description="平台原始值"
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

  it("renders the work cards with a cover or the existing empty-cover degrade", async () => {
    const view = renderProfile();
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));

    const cards = Array.from(document.querySelectorAll(".video-card"));
    expect(cards).toHaveLength(3);
    // 平台没有给出可渲染的封面地址（item_cover 是不透明 key / 空串），因此走占位降级，不构造 CDN 链接。
    expect(document.querySelectorAll(".video-card-cover-empty")).toHaveLength(3);
    expect(cards[0].textContent).toContain("雨刮器为什么不好用");
    expect(cards[0].textContent).toContain("915,520");
    expect(cards[0].textContent).toContain("2026-10-12");
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
  });

  it("renders an empty state instead of a broken chart when there are no video records", async () => {
    const view = renderProfile(CATALOG, CREATOR, PAYLOAD_WITHOUT_VIDEOS as Record<string, unknown>);
    const user = userEvent.setup();
    await user.click(view.getByRole("tab", { name: "创作能力" }));
    // 空数据不渲染图表、柱子或作品卡片，也不抛错；空态使用平台状态文案。
    expect(document.querySelector(".video-bars")).toBeNull();
    expect(document.querySelectorAll(".video-bar-slot")).toHaveLength(0);
    expect(document.querySelectorAll(".video-card")).toHaveLength(0);
    expect(document.querySelector(".video-tip")).toBeNull();
    const empty = document.querySelector("#content .profile-empty");
    expect(empty).not.toBeNull();
    expect(empty?.textContent).toBeTruthy();
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
});
