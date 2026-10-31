import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const user = {
  user_id: "user-a", username: "media-a", display_name: "媒介 A", csrf_token: "csrf-token",
};

const task = {
  root_task_id: "11111111-1111-4111-8111-111111111111",
  status: "COLLECTING",
  stage: "采集达人资料",
  version: 3,
  created_at: "2026-10-10T02:00:00Z",
  updated_at: "2026-10-10T02:05:00Z",
  completed_at: null,
  created_by: "user-a",
  created_by_name: "媒介 A",
  source: "product",
  keyword: "宠物",
  counts: { target_count: 20, discovered_count: 31, valid_count: 8, profile_complete_count: 6, featured_complete_count: 4, failed_count: 1 },
  allowed_actions: ["cancel"],
  failure_reason: null,
};

const taskDetail = {
  ...task,
  requirement: null,
  capability_version: "live-v1",
  plan: null,
  field_errors: [],
  origin_root_task_id: null,
  challenge: null,
};

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
}

describe("M3 product application", () => {
  beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); });
  // Several tests render the whole app; unmount so a later test never queries a stale tree.
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("restores the authenticated shared task list with distinct progress counts", async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path.startsWith("/api/tasks?")) return json({ items: [task], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks");
    expect(await screen.findByRole("heading", { name: "任务中心" })).toBeInTheDocument();
    expect(await screen.findByText("宠物")).toBeInTheDocument();
    expect(screen.getByText("采集达人资料")).toBeInTheDocument();
    expect(screen.getByText("31")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
  });

  it("filters the task center by platform and keeps juxing rows free of featured counts", async () => {
    const paths: string[] = [];
    const juxingTask = {
      ...task,
      root_task_id: "22222222-2222-4222-8222-222222222222",
      platform: "kuaishou_juxing",
      task_kind: "collection",
      keyword: "母婴",
      counts: { target_count: 1, discovered_count: 3, valid_count: 1, profile_complete_count: 1, featured_complete_count: 0, failed_count: 0 },
    };
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      paths.push(path);
      if (path === "/api/auth/me") return json(user);
      if (path.startsWith("/api/tasks?")) return json({ items: [juxingTask], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks");
    expect(await screen.findByRole("heading", { name: "任务中心" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "按平台筛选" }), "kuaishou_juxing");
    await waitFor(() => expect(paths.some((path) => path.includes("platform=kuaishou_juxing"))).toBe(true));
    const row = await screen.findByRole("row", { name: /母婴/ });
    expect(within(row).getByText(/磁力聚星/)).toBeInTheDocument();
    expect(within(row).queryByText("精选")).not.toBeInTheDocument();
    expect(within(row).queryByText("0")).not.toBeInTheDocument();
  });

  it("renders only server-enabled capabilities and submits one idempotent task", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input); calls.push({ path, init });
      if (path === "/api/auth/me") return json(user);
      if (path === "/api/platforms/douyin_xingtu/capabilities") return json({
        platform: "douyin_xingtu", capability_version: "live-v1",
        fields: [{ field: "keyword", label: "内容关键词", operators: ["eq"], options: [], currencies: [], cooperation_forms: [], keyword_mode: "content" }],
        combinations: [["keyword"]], target_count_default: 20, target_count_min: 1,
        target_count_max: 200, fixed_sort_key: "score", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/tasks" && init?.method === "POST") return json({ root_task_id: task.root_task_id, status: "RECEIVED" }, 202);
      if (path === `/api/tasks/${task.root_task_id}`) return json({ ...task, status: "RECEIVED", stage: "需求已接收", requirement: { keyword: "宠物" }, capability_version: "live-v1", plan: null, field_errors: [], origin_root_task_id: null });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks/new");
    const keyword = await screen.findByPlaceholderText("例如：宠物、母婴辅食、户外露营");
    expect(screen.getByRole("radio", { name: /巨量星图/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: /磁力聚星/ })).toBeDisabled();
    expect(screen.getByText("能力已观察，尚待验证")).toBeInTheDocument();
    expect(screen.queryByText("达人类型")).not.toBeInTheDocument();
    await userEvent.type(keyword, "宠物");
    await userEvent.click(screen.getByRole("button", { name: /提交采集任务/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/api/tasks" && call.init?.method === "POST")).toBe(true));
    const create = calls.find((call) => call.path === "/api/tasks" && call.init?.method === "POST")!;
    expect(new Headers(create.init?.headers).get("Idempotency-Key")).toBe("00000000-0000-4000-8000-000000000001");
    expect(JSON.parse(String(create.init?.body))).toMatchObject({ keyword: "宠物", target_count: 20 });
  });

  it("switches to the verified Juxing contract and submits a single-platform v3 task", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input); calls.push({ path, init });
      if (path === "/api/auth/me") return json(user);
      if (path === "/api/platforms") return json([
        { platform: "douyin_xingtu", label: "巨量星图", enabled: true, capability_status: "verified", contract_version: "live-v2" },
        { platform: "kuaishou_juxing", label: "磁力聚星", enabled: true, capability_status: "verified", contract_version: "juxing-stage-b-v1" },
      ]);
      if (path === "/api/platforms/douyin_xingtu/capabilities") return json({
        platform: "douyin_xingtu", capability_version: "live-v2",
        fields: [{ field: "keyword", label: "内容关键词", operators: ["eq"], options: [], currencies: [], cooperation_forms: [], keyword_mode: "content" }],
        combinations: [["keyword"]], target_count_default: 20, target_count_min: 1,
        target_count_max: 200, fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/platforms/kuaishou_juxing/capabilities") return json({
        platform: "kuaishou_juxing", capability_version: "juxing-video-square-stage-b-v1",
        fields: [
          { field: "keyword", label: "内容关键词", operators: ["eq"], options: [], currencies: [], cooperation_forms: [], keyword_mode: "content" },
          { field: "content_type", label: "内容类型", operators: ["in"], options: [{ value: "maternal_child", label: "母婴亲子" }], currencies: [], cooperation_forms: [] },
        ],
        combinations: [["keyword"], ["content_type"], ["keyword", "content_type"]],
        target_count_default: 3, target_count_min: 1, target_count_max: 3,
        fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/tasks" && init?.method === "POST") return json({ root_task_id: task.root_task_id, status: "RECEIVED" }, 202);
      if (path === `/api/tasks/${task.root_task_id}`) return json({ ...taskDetail, status: "RECEIVED" });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks/new");
    const juxing = await screen.findByRole("radio", { name: /磁力聚星/ });
    expect(juxing).toBeEnabled();
    await userEvent.click(juxing);
    const keyword = await screen.findByPlaceholderText("例如：母婴");
    await userEvent.type(keyword, "母婴");
    await userEvent.selectOptions(screen.getByRole("combobox"), "maternal_child");
    await userEvent.click(screen.getByRole("button", { name: /提交采集任务/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/api/tasks" && call.init?.method === "POST")).toBe(true));
    const create = calls.find((call) => call.path === "/api/tasks" && call.init?.method === "POST")!;
    expect(JSON.parse(String(create.init?.body))).toMatchObject({
      schema_version: "requirement_form.v3", platform: "kuaishou_juxing",
      keyword: "母婴", content_types: ["maternal_child"], target_count: 3,
    });
  });

  it("submits juxing followers, region and quote ranges from the verified controls", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const base = { operators: [], options: [], dimensions: [], region_tree: [], incompatible_with: [], currencies: [], cooperation_forms: [] };
    const capFields = [
      { ...base, field: "keyword", label: "内容关键词", operators: ["eq"], keyword_mode: "content" },
      { ...base, field: "content_type", label: "内容类型", operators: ["in"], control: "single-select", options: [{ value: "maternal_child", label: "母婴亲子" }, { value: "670", label: "美妆" }] },
      { ...base, field: "followers", label: "粉丝数量", operators: ["range"], control: "range", unit: "count", range_constraints: { min: 0, max: 100000000, unit: "count" }, options: [{ value: "10w_100w", label: "10万-100万", range: { min: 100000, max: 1000000 } }, { value: "under_10w", label: "10万以下", range: { min: 0, max: 100000 } }] },
      { ...base, field: "region", label: "达人地域", operators: ["compound"], control: "cascader", region_tree: [{ value: "11", label: "北京", children: [{ value: "1101", label: "北京", children: [] }] }] },
      { ...base, field: "video_quote_1_20", label: "1-20秒视频报价", operators: ["range"], control: "range", unit: "yuan", currencies: ["CNY"], cooperation_forms: ["short_video_1_20s"], range_constraints: { min: 0, max: 1000000, unit: "yuan" } },
      { ...base, field: "video_quote_21_60", label: "21-60秒视频报价", operators: ["range"], control: "range", unit: "yuan", currencies: ["CNY"], cooperation_forms: ["short_video_21_60s"], range_constraints: { min: 0, max: 1000000, unit: "yuan" } },
      { ...base, field: "video_quote_60_plus", label: "60秒以上视频报价", operators: ["range"], control: "range", unit: "yuan", currencies: ["CNY"], cooperation_forms: ["short_video_60s_plus"], range_constraints: { min: 0, max: 1000000, unit: "yuan" } },
    ];
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input); calls.push({ path, init });
      if (path === "/api/auth/me") return json(user);
      if (path === "/api/platforms") return json([
        { platform: "douyin_xingtu", label: "巨量星图", enabled: true, capability_status: "verified", contract_version: "live-v2" },
        { platform: "kuaishou_juxing", label: "磁力聚星", enabled: true, capability_status: "verified", contract_version: "juxing-stage-c-v2" },
      ]);
      if (path === "/api/platforms/douyin_xingtu/capabilities") return json({
        platform: "douyin_xingtu", capability_version: "live-v2",
        fields: [{ ...base, field: "keyword", label: "内容关键词", operators: ["eq"], keyword_mode: "content" }],
        combinations: [["keyword"]], target_count_default: 20, target_count_min: 1, target_count_max: 200,
        fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/platforms/kuaishou_juxing/capabilities") return json({
        platform: "kuaishou_juxing", capability_version: "juxing-video-square-stage-c-v2", fields: capFields,
        combinations: [], combination_policy: { schema_version: "combination_policy.v2", mode: "composable", fields: ["keyword", "content_type", "followers", "region", "video_quote_1_20", "video_quote_21_60", "video_quote_60_plus"], incompatible: [] },
        target_count_default: 3, target_count_min: 1, target_count_max: 30,
        fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/tasks" && init?.method === "POST") return json({ root_task_id: task.root_task_id, status: "RECEIVED" }, 202);
      if (path === `/api/tasks/${task.root_task_id}`) return json({ ...taskDetail, status: "RECEIVED" });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks/new");
    await userEvent.click(await screen.findByRole("radio", { name: /磁力聚星/ }));
    await userEvent.type(await screen.findByPlaceholderText("例如：母婴"), "母婴");
    await userEvent.selectOptions(screen.getByLabelText("内容类型"), "maternal_child");
    await userEvent.selectOptions(screen.getByLabelText("粉丝数量"), "10w_100w");
    await userEvent.selectOptions(screen.getByLabelText("省级地域"), "11");
    await userEvent.selectOptions(screen.getByLabelText("报价档位"), "seconds_21_60");
    await userEvent.type(screen.getByLabelText("报价上限（元）"), "10000");
    await userEvent.click(screen.getByRole("button", { name: /提交采集任务/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/api/tasks" && call.init?.method === "POST")).toBe(true));
    const create = calls.find((call) => call.path === "/api/tasks" && call.init?.method === "POST")!;
    expect(JSON.parse(String(create.init?.body))).toMatchObject({
      schema_version: "requirement_form.v3", platform: "kuaishou_juxing", keyword: "母婴",
      content_types: ["maternal_child"],
      followers: { min: 100000, max: 1000000, unit: "count" },
      creator_regions: [{ province_code: "11" }],
      juxing_video_quotes: { seconds_1_20: null, seconds_21_60: { min: null, max: 10000, unit: "yuan" }, seconds_60_plus: null },
    });
  });

  it("keeps the newly picked juxing quote tier usable and drops the previous tier's range", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const base = { operators: [], options: [], dimensions: [], region_tree: [], incompatible_with: [], currencies: [], cooperation_forms: [] };
    const quote = (field: string, label: string, cooperation: string) => ({
      ...base, field, label, operators: ["range"], control: "range", unit: "yuan", currencies: ["CNY"],
      cooperation_forms: [cooperation], range_constraints: { min: 0, max: 1000000, unit: "yuan" },
    });
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input); calls.push({ path, init });
      if (path === "/api/auth/me") return json(user);
      if (path === "/api/platforms") return json([
        { platform: "douyin_xingtu", label: "巨量星图", enabled: true, capability_status: "verified", contract_version: "live-v2" },
        { platform: "kuaishou_juxing", label: "磁力聚星", enabled: true, capability_status: "verified", contract_version: "juxing-stage-c-v2" },
      ]);
      if (path === "/api/platforms/douyin_xingtu/capabilities") return json({
        platform: "douyin_xingtu", capability_version: "live-v2",
        fields: [{ ...base, field: "keyword", label: "内容关键词", operators: ["eq"], keyword_mode: "content" }],
        combinations: [["keyword"]], target_count_default: 20, target_count_min: 1, target_count_max: 200,
        fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/platforms/kuaishou_juxing/capabilities") return json({
        platform: "kuaishou_juxing", capability_version: "juxing-video-square-stage-c-v2",
        fields: [
          quote("video_quote_1_20", "1-20秒视频报价", "short_video_1_20s"),
          quote("video_quote_21_60", "21-60秒视频报价", "short_video_21_60s"),
          quote("video_quote_60_plus", "60秒以上视频报价", "short_video_60s_plus"),
        ],
        combinations: [], combination_policy: {
          schema_version: "combination_policy.v2", mode: "composable",
          fields: ["video_quote_1_20", "video_quote_21_60", "video_quote_60_plus"],
          incompatible: [["video_quote_1_20", "video_quote_21_60"]],
        },
        target_count_default: 3, target_count_min: 1, target_count_max: 30,
        fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/tasks" && init?.method === "POST") return json({ root_task_id: task.root_task_id, status: "RECEIVED" }, 202);
      if (path === `/api/tasks/${task.root_task_id}`) return json({ ...taskDetail, status: "RECEIVED" });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks/new");
    await userEvent.click(await screen.findByRole("radio", { name: /磁力聚星/ }));
    await userEvent.selectOptions(await screen.findByLabelText("报价档位"), "seconds_21_60");
    await userEvent.type(screen.getByLabelText("报价上限（元）"), "10000");
    // The tiers are mutually exclusive, so switching drops the old range for real.  The control
    // must still follow the operator to the tier they picked instead of snapping back to 全部/不限.
    await userEvent.selectOptions(screen.getByLabelText("报价档位"), "seconds_60_plus");
    expect(screen.getByLabelText("报价档位")).toHaveValue("seconds_60_plus");
    await userEvent.type(screen.getByLabelText("报价下限（元）"), "5000");
    await userEvent.click(screen.getByRole("button", { name: /提交采集任务/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/api/tasks" && call.init?.method === "POST")).toBe(true));
    const create = calls.find((call) => call.path === "/api/tasks" && call.init?.method === "POST")!;
    expect(JSON.parse(String(create.init?.body))).toMatchObject({
      platform: "kuaishou_juxing",
      juxing_video_quotes: { seconds_1_20: null, seconds_21_60: null, seconds_60_plus: { min: 5000, max: null, unit: "yuan" } },
    });
  });

  it("uses the server-configured juxing target ceiling for an authorized 10-creator run", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input); calls.push({ path, init });
      if (path === "/api/auth/me") return json(user);
      if (path === "/api/platforms") return json([
        { platform: "douyin_xingtu", label: "巨量星图", enabled: true, capability_status: "verified", contract_version: "live-v2" },
        { platform: "kuaishou_juxing", label: "磁力聚星", enabled: true, capability_status: "verified", contract_version: "juxing-stage-b-v1" },
      ]);
      if (path === "/api/platforms/douyin_xingtu/capabilities") return json({
        platform: "douyin_xingtu", capability_version: "live-v2",
        fields: [{ field: "keyword", label: "内容关键词", operators: ["eq"], options: [], currencies: [], cooperation_forms: [], keyword_mode: "content" }],
        combinations: [["keyword"]], target_count_default: 20, target_count_min: 1,
        target_count_max: 200, fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/platforms/kuaishou_juxing/capabilities") return json({
        platform: "kuaishou_juxing", capability_version: "juxing-video-square-stage-b-v1",
        fields: [
          { field: "keyword", label: "内容关键词", operators: ["eq"], options: [], currencies: [], cooperation_forms: [], keyword_mode: "content" },
          { field: "content_type", label: "内容类型", operators: ["in"], options: [{ value: "maternal_child", label: "母婴亲子" }], currencies: [], cooperation_forms: [] },
        ],
        combinations: [["keyword"], ["content_type"], ["keyword", "content_type"]],
        target_count_default: 3, target_count_min: 1, target_count_max: 10,
        fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/tasks" && init?.method === "POST") return json({ root_task_id: task.root_task_id, status: "RECEIVED" }, 202);
      if (path === `/api/tasks/${task.root_task_id}`) return json({ ...taskDetail, status: "RECEIVED" });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks/new");
    await userEvent.click(await screen.findByRole("radio", { name: /磁力聚星/ }));
    await userEvent.type(await screen.findByPlaceholderText("例如：母婴"), "母婴");
    await userEvent.selectOptions(screen.getByRole("combobox"), "maternal_child");
    const target = screen.getByRole("spinbutton");
    expect(target).toHaveAttribute("max", "10");
    fireEvent.change(target, { target: { value: "10" } });
    await userEvent.click(screen.getByRole("button", { name: /提交采集任务/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/api/tasks" && call.init?.method === "POST")).toBe(true));
    const create = calls.find((call) => call.path === "/api/tasks" && call.init?.method === "POST")!;
    expect(JSON.parse(String(create.init?.body))).toMatchObject({
      schema_version: "requirement_form.v3", platform: "kuaishou_juxing", target_count: 10,
    });
  });

  it("renders v2 background and audience controls and enforces profile exclusivity", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const option = (value: string, label: string) => ({ value, label, request_value: null, range: null });
    const emptyMeta = { operators: ["eq"], dimensions: [], region_tree: [], range_constraints: null, incompatible_with: [], unit: null, currencies: [], cooperation_forms: [], keyword_mode: null };
    const profileDimensions = [
      { key: "age", label: "年龄", control: "multi-select", options: [option("age_18_23", "18-23岁居多")], range_constraints: null },
      { key: "gender", label: "性别", control: "single-select", options: [option("female_60", "女性占比大于60%")], range_constraints: null },
      { key: "device_brand", label: "设备品牌", control: "multi-select", options: [option("apple", "苹果居多")], range_constraints: null },
      { key: "city_level", label: "地域", control: "multi-select", options: [option("tier_1", "一线城市居多")], range_constraints: null },
      { key: "crowd", label: "八大人群", control: "multi-select", options: [option("gen_z", "Z世代")], range_constraints: null },
    ];
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input); calls.push({ path, init });
      if (path === "/api/auth/me") return json(user);
      if (path === "/api/platforms/douyin_xingtu/capabilities") return json({
        platform: "douyin_xingtu", capability_version: "live-v2",
        fields: [
          { field: "keyword", label: "内容关键词", control: "text", options: [], ...emptyMeta, keyword_mode: "content" },
          { field: "gender", label: "达人性别", group: "背景信息", control: "single-select", options: [option("male", "男性"), option("female", "女性")], ...emptyMeta },
          { field: "region", label: "所在地域", group: "背景信息", control: "cascader", options: [], ...emptyMeta, region_tree: [{ value: "110000", label: "北京市", children: [{ value: "朝阳区", label: "朝阳区", children: [] }] }] },
          { field: "education", label: "学历", group: "背景信息", control: "single-select", options: [option("master", "硕士生")], ...emptyMeta },
          { field: "yellow_v", label: "黄v认证", group: "背景信息", control: "single-select", options: [option("technology", "科技创作者")], ...emptyMeta },
          { field: "followers", label: "粉丝量级", group: "受众画像", control: "range", options: [{ value: "10_100", label: "10w-100w", request_value: null, range: { min: "10", max: "100" } }], ...emptyMeta, range_constraints: { min: 0, max: 5000, unit: "ten_thousand_count" } },
          { field: "connection_users", label: "连接用户数", group: "受众画像", control: "range-group", options: [], ...emptyMeta, dimensions: [
            { key: "connected", label: "连接用户数", control: "range", options: [], range_constraints: { min: 0, max: 99999, unit: "ten_thousand_count" } },
          ] },
          { field: "viewer_profile", label: "观众画像", group: "受众画像", control: "profile-group", options: [], ...emptyMeta, dimensions: profileDimensions, incompatible_with: ["fan_profile"] },
          { field: "fan_profile", label: "粉丝画像", group: "受众画像", control: "profile-group", options: [], ...emptyMeta, dimensions: profileDimensions, incompatible_with: ["viewer_profile"] },
        ],
        combinations: [["keyword"]], combination_policy: { schema_version: "combination_policy.v2", mode: "composable", fields: [], incompatible: [["viewer_profile", "fan_profile"]] },
        target_count_default: 20, target_count_min: 1, target_count_max: 200,
        fixed_sort_key: "score", fixed_sort_label: "平台默认排序",
      });
      if (path === "/api/tasks" && init?.method === "POST") return json({ root_task_id: task.root_task_id, status: "RECEIVED" }, 202);
      if (path === `/api/tasks/${task.root_task_id}`) return json({ ...taskDetail, status: "RECEIVED" });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks/new");
    expect(await screen.findByText("背景信息")).toBeInTheDocument();
    expect(screen.getByText("巨量星图仅允许观众画像与粉丝画像二选一；选择一侧会清空另一侧。")).toBeInTheDocument();
    const rangeInputs = screen.getAllByLabelText("下限");
    expect(rangeInputs.length).toBeGreaterThan(0);
    for (const input of rangeInputs) {
      expect(input).toHaveAttribute("step", "any");
      expect(input).toHaveAttribute("max", "99999");
    }
    await userEvent.type(screen.getAllByLabelText("上限")[0], "99999");
    await userEvent.selectOptions(screen.getByText("达人性别").closest("label")!.querySelector("select")!, "female");
    await userEvent.selectOptions(screen.getByLabelText("省级地域"), "110000");
    expect(await screen.findByRole("button", { name: "北京市 ×" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("二级地域"), "朝阳区");
    expect(await screen.findByRole("button", { name: "北京市 / 朝阳区 ×" })).toBeInTheDocument();
    expect(screen.getByText("所在地域：1 项")).toBeInTheDocument();
    const ages = screen.getAllByLabelText("18-23岁居多");
    await userEvent.click(ages[0]);
    expect(ages[0]).toBeChecked();
    const crowds = screen.getAllByLabelText("Z世代");
    await userEvent.click(crowds[1]);
    expect(ages[0]).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: /提交采集任务/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/api/tasks" && call.init?.method === "POST")).toBe(true));
    const create = calls.find((call) => call.path === "/api/tasks" && call.init?.method === "POST")!;
    expect(JSON.parse(String(create.init?.body))).toMatchObject({
      schema_version: "requirement_form.v2",
      creator_gender: "female",
      creator_regions: [{ province_code: "110000", city: "朝阳区" }],
      connection_users: { connected: { max: 99999, unit: "ten_thousand_count" } },
      viewer_profile: null,
      fan_profile: { crowd: ["gen_z"] },
    });
  });

  it("surfaces security verification custody on task detail", async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path === `/api/tasks/${task.root_task_id}`) return json({
        ...taskDetail,
        status: "WAITING_FOR_VERIFICATION",
        stage: "等待安全验证",
        failure_reason: "PLATFORM_SECURITY_CHALLENGE",
        allowed_actions: ["cancel"],
        challenge: {
          state: "HANDLING",
          challenge_type: "SLIDER_OR_INTERACTIVE",
          first_detected_at: "2026-10-10T02:01:00Z",
          last_detected_at: "2026-10-10T02:02:00Z",
          wait_started_at: "2026-10-10T02:02:00Z",
          last_recovered_at: null,
          detected_count: 2,
          recovery_count: 1,
          current_creator_id: "creator-1",
          completed_creator_count: 1,
          remaining_creator_count: 12,
          waiting_seconds: 75,
          account_matches: null,
          requires_user_action: true,
          monitoring: true,
          terminal_reason: null,
          terminal_message: null,
          delivered_result: "已保留 8 位达人及其已持久数据",
        },
      });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp(`/tasks/${task.root_task_id}`);
    // The status badge and the hero heading both carry the status label by design.
    expect((await screen.findAllByText("等待安全验证")).length).toBeGreaterThan(0);
    expect(await screen.findByText("安全验证托管")).toBeInTheDocument();
    expect(screen.getAllByText("等待处理").length).toBeGreaterThan(0);
    expect(screen.getByText("当前达人 creator-1")).toBeInTheDocument();
    expect(screen.getByText("已保留 8 位达人及其已持久数据")).toBeInTheDocument();
  });

  it("renders creator-library raw values and incomplete-data state", async () => {
    const rawMetric = { value: 428, raw_value: "428", unit: null, is_approximate: false, status: "COLLECTED", observed_at: "2026-10-12T08:08:00Z" };
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path.startsWith("/api/creator-library?")) return json({ items: [{
        creator_id: "22222222-2222-4222-8222-222222222222", platform: "douyin_xingtu", platform_creator_id: "sample", display_name: "达人 A", avatar_uri: null,
        creator_type_label: "生活", province: "北京市", city: "朝阳区", industry_labels: ["食品饮料"],
        followers: { ...rawMetric, value: 5704674, raw_value: "5704674", unit: "count" },
        monthly_deep_users: { ...rawMetric, value: 48899000, raw_value: "4,889.9w", unit: "count", is_approximate: true },
        monthly_connected_users: rawMetric, monthly_follower_growth_rate: rawMetric, interaction_rate: rawMetric, completion_rate: { ...rawMetric, value: 6343, raw_value: "6343" },
        expected_cpm_21_60: { ...rawMetric, value: 10029, raw_value: "10029" }, expected_cpm_60_plus: rawMetric,
        expected_cpe_21_60: { ...rawMetric, value: 934, raw_value: "934" }, expected_cpe_60_plus: rawMetric,
        profile_complete: false, pipeline_complete: true, data_updated_at: "2026-10-12T08:09:00Z",
      }], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/creators");
    expect(await screen.findByRole("heading", { name: "达人库" })).toBeInTheDocument();
    expect(await screen.findByText("达人 A")).toBeInTheDocument();
    expect(screen.getByText("≈4,889.9w")).toBeInTheDocument();
    // The Xingtu row keeps its original「达人类型 · 地区」line; the platform name belongs to the
    // page filter, not to the row identity.
    expect(screen.getByText("生活 · 北京市 / 朝阳区")).toBeInTheDocument();
    expect(screen.getByText("数据不完整")).toBeInTheDocument();
    expect(screen.getAllByText("CPM / CPE 原始值").length).toBeGreaterThan(0);
  });

  it("shows independent worker health and local original-Chrome takeover guidance", async () => {
    const unit = {
      unit_id: "unit-local-win-01", platform: "douyin_xingtu", account_label: "•••acct",
      line_label: "•••local", state: "LEASED", mode: "maintenance",
      allowed_task_kinds: ["collection"], current_root_task_id: task.root_task_id,
      worker_status: "ONLINE", worker_instances: 1,
      worker_last_heartbeat_at: "2026-10-23T02:00:00Z", browser_status: "MAINTENANCE",
      verification_state: "OPEN", takeover_state: null,
      verification_deadline_at: "2026-10-23T03:00:00Z",
      last_heartbeat_at: "2026-10-23T02:00:00Z", actionable_reason: "PLATFORM_SECURITY_CHALLENGE",
    };
    const takeover = {
      takeover_id: "22222222-2222-4222-8222-222222222222", unit_id: unit.unit_id,
      root_task_id: task.root_task_id, state: "ACTIVE", expires_at: "2026-10-23T03:00:00Z",
      failure_reason: null, viewer_url: null, access_mode: "LOCAL_WINDOW",
      operator_message: "请切换到本机已经打开的执行单元 Chrome 窗口完成验证。",
      manual_probe_creators: [],
    };
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path === "/api/execution-units") return json([unit]);
      if (path === "/api/verification-events?open_only=true") return json([{
        event_id: "33333333-3333-4333-8333-333333333333", unit_id: unit.unit_id,
        root_task_id: task.root_task_id, state: "OPEN", reason: "PLATFORM_SECURITY_CHALLENGE",
        detected_at: "2026-10-23T02:00:00Z", last_detected_at: "2026-10-23T02:00:00Z",
        deadline_at: "2026-10-23T03:00:00Z", reappearance_count: 0, remaining_seconds: 600,
      }]);
      if (path === `/api/execution-units/${unit.unit_id}/takeovers` && init?.method === "POST") return json(takeover, 202);
      if (path === `/api/takeovers/${takeover.takeover_id}`) return json(takeover);
      return json({}, 404);
    });
    renderApp("/execution-units");
    expect(await screen.findByText("ONLINE")).toBeInTheDocument();
    expect(screen.getByText(/1 实例/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "接管浏览器" }));
    expect(await screen.findByText("请切换到本机原 Chrome 窗口")).toBeInTheDocument();
    expect(screen.getByText("请切换到本机已经打开的执行单元 Chrome 窗口完成验证。")).toBeInTheDocument();
    expect(screen.queryByTitle("原 Chromium 浏览器")).not.toBeInTheDocument();
  });
});

describe("UI-01 page optimisations", () => {
  it("keeps the password hidden until the toggle is used, without clearing input", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      calls.push({ path, init });
      if (path === "/api/auth/me") return json({}, 401);
      if (path === "/api/auth/login" && init?.method === "POST") return json(user);
      if (path.startsWith("/api/tasks?")) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/login");
    const username = await screen.findByPlaceholderText("请输入账号");
    fireEvent.change(username, { target: { value: "media-a" } });
    const password = await screen.findByPlaceholderText("请输入密码");
    expect(password).toHaveAttribute("type", "password");
    fireEvent.change(password, { target: { value: "s3cret-pass" } });
    await waitFor(() => expect(screen.getByPlaceholderText("请输入密码")).toHaveValue("s3cret-pass"));

    await userEvent.click(screen.getByRole("button", { name: "显示密码" }));
    await waitFor(() => expect(screen.getByPlaceholderText("请输入密码")).toHaveAttribute("type", "text"));
    expect(screen.getByPlaceholderText("请输入密码")).toHaveValue("s3cret-pass");

    // Toggling back must not clear what the user already typed.
    await userEvent.click(screen.getByRole("button", { name: "隐藏密码" }));
    await waitFor(() => expect(screen.getByPlaceholderText("请输入密码")).toHaveAttribute("type", "password"));
    expect(screen.getByPlaceholderText("请输入密码")).toHaveValue("s3cret-pass");
    // The original login path still submits exactly the credential the user typed.
    await userEvent.click(screen.getByRole("button", { name: /安全登录/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/api/auth/login")).toBe(true));
    const login = calls.find((call) => call.path === "/api/auth/login")!;
    expect(JSON.parse(String(login.init?.body))).toEqual({ username: "media-a", password: "s3cret-pass" });
  });

  it("drops the duplicate 创建任务 nav entry and keeps the in-page entry", async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path.startsWith("/api/tasks?")) return json({ items: [task], next_cursor: null });
      return json({}, 404);
    });
    renderApp("/tasks");
    const nav = await screen.findByRole("navigation", { name: "主导航" });
    expect(nav).toHaveTextContent("任务中心");
    expect(nav).toHaveTextContent("达人库");
    expect(nav).not.toHaveTextContent("创建任务");
    // The task-centre header button and the empty-state action still own the create flow.
    expect(screen.getAllByRole("link", { name: /创建任务/ }).length).toBeGreaterThan(0);
  });

  it("shows the same library metrics for a creator inside a task snapshot", async () => {
    const payload = {
      profile_complete: true,
      pipeline_complete: true,
      modules: {
        basic: {
          status: "COLLECTED",
          fields: [
            { field_key: "nickname", value: "甄选聊车", status: "COLLECTED" },
            { field_key: "avatar_uri", value: "https://example.test/avatar.jpg", status: "COLLECTED" },
            { field_key: "creator_type_label", value: "汽车", status: "COLLECTED" },
            { field_key: "industry_labels", value: ["金融业", "美妆"], status: "COLLECTED" },
            { field_key: "followers", value: { kind: "number", bound: "exact", amount: "1351784" }, raw_value: "1351784", status: "COLLECTED" },
            { field_key: "monthly_deep_users", value: { kind: "number", bound: "approximate", amount: "11580000" }, raw_value: "1,158w", is_approximate: true, status: "COLLECTED" },
            { field_key: "mcn_name", value: null, status: "NO_DATA" },
          ],
        },
        spread: {
          status: "COLLECTED",
          fields: [
            { field_key: "interaction_rate", value: { kind: "structured", data: { value: 112 } }, raw_value: '{"value":112}', status: "COLLECTED" },
            { field_key: "completion_rate", value: { kind: "structured", data: { value: 551 } }, raw_value: '{"value":551}', status: "COLLECTED" },
            { field_key: "expected_cpm", value: { kind: "structured", data: { cpm_21_60: "2969", cpm_60: "3836" } }, raw_value: "{}", status: "COLLECTED" },
            { field_key: "expected_cpe", value: { kind: "structured", data: { cpe_21_60: "246", cpe_60: "310" } }, raw_value: "{}", status: "COLLECTED" },
          ],
        },
      },
    };
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators?`)) return json({
        items: [{
          creator_id: "33333333-3333-4333-8333-333333333333",
          platform_creator_id: "7503176021160493065",
          first_position: 0,
          view_kind: "published",
          snapshot_id: "44444444-4444-4444-8444-444444444444",
          observed_at: "2026-10-14T01:56:05Z",
          payload,
        }],
        next_cursor: null,
      });
      if (path === `/api/tasks/${task.root_task_id}`) return json(taskDetail);
      return json({}, 404);
    });
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByRole("heading", { name: "任务内达人" })).toBeInTheDocument();
    const row = await screen.findByRole("link", { name: /查看达人 甄选聊车 详情/ });
    expect(row).toHaveTextContent("汽车 · 金融业 · 美妆");
    expect(row).toHaveTextContent("1,351,784");
    expect(row).toHaveTextContent("≈1,158w");
    expect(row).toHaveTextContent("112 / 551");
    expect(row).toHaveTextContent("2969 / 246");
    // The library's own label and unit wording, not a task-only variant.
    expect(row).toHaveTextContent("CPM / CPE 原始值");
    expect(row).toHaveTextContent("互动 / 完播原始值");
  });

  it("labels the completion moment separately from the last-update audit value", async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path === `/api/tasks/${task.root_task_id}`) return json({
        ...taskDetail,
        status: "COMPLETED",
        stage: "已完成",
        allowed_actions: [],
        completed_at: "2026-10-10T02:31:00Z",
      });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByText("首次完成时间")).toBeInTheDocument();
    expect(screen.getAllByText("最近更新").length).toBeGreaterThan(0);
  });

  it("renders an update batch with per-creator state and no requirement panel", async () => {
    const updateTask = {
      ...taskDetail,
      task_kind: "manual_update",
      capability_version: null,
      keyword: null,
      status: "PARTIAL_COMPLETED",
      stage: "部分完成",
      allowed_actions: [],
      counts: {
        ...task.counts,
        target_count: 2,
        valid_count: 1,
        profile_complete_count: 1,
        featured_complete_count: 1,
        failed_count: 1,
      },
      update_targets: [
        { creator_id: "creator-1", platform_creator_id: "1001", display_name: null, first_position: 0, state: "done", failure_reason: null },
        { creator_id: "creator-2", platform_creator_id: "1002", display_name: null, first_position: 1, state: "invalid", failure_reason: "CREATOR_INVALID" },
      ],
    };
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path === `/api/tasks/${task.root_task_id}`) return json(updateTask);
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByRole("heading", { name: /手动更新 · 2 位达人/ })).toBeInTheDocument();
    expect(screen.getByText("更新目标")).toBeInTheDocument();
    expect(screen.getAllByText("已完成").length).toBeGreaterThan(0);
    expect(screen.getByText("达人无效")).toBeInTheDocument();
    expect(screen.getByText("CREATOR_INVALID")).toBeInTheDocument();
    expect(screen.getByText("更新任务不适用")).toBeInTheDocument();
    expect(screen.queryByText("历史任务")).not.toBeInTheDocument();
  });

  it("renders one shared creator detail for both entry points", async () => {
    // CD-07: 记录实际发出的请求，用于断言页面已不再消费「系统采集历史」接口。
    const requestedPaths: string[] = [];
    const libraryCreator = {
      creator_id: "33333333-3333-4333-8333-333333333333",
      platform: "douyin_xingtu",
      platform_creator_id: "7503176021160493065",
      display_name: "甄选聊车",
      avatar_uri: null,
      creator_type_label: "汽车",
      province: "内蒙古自治区",
      city: "赤峰市",
      industry_labels: ["金融业"],
      mcn_name: null,
      introduction: "关注我",
      gender: "1",
      content_theme_labels: ["用车知识"],
      followers: { value: 1351784, raw_value: "1351784", unit: "count", is_approximate: false, status: "COLLECTED", observed_at: null },
      monthly_deep_users: { value: 11580000, raw_value: "1,158w", unit: "count", is_approximate: true, status: "COLLECTED", observed_at: null },
      monthly_connected_users: { value: null, raw_value: null, unit: null, is_approximate: false, status: "NO_DATA", observed_at: null },
      monthly_follower_growth_rate: { value: null, raw_value: null, unit: null, is_approximate: false, status: "NO_DATA", observed_at: null },
      interaction_rate: { value: 112, raw_value: "112", unit: null, is_approximate: false, status: "COLLECTED", observed_at: null },
      completion_rate: { value: 551, raw_value: "551", unit: null, is_approximate: false, status: "COLLECTED", observed_at: null },
      expected_cpm_21_60: { value: 2969, raw_value: "2969", unit: null, is_approximate: false, status: "COLLECTED", observed_at: null },
      expected_cpm_60_plus: { value: 3836, raw_value: "3836", unit: null, is_approximate: false, status: "COLLECTED", observed_at: null },
      expected_cpe_21_60: { value: 246, raw_value: "246", unit: null, is_approximate: false, status: "COLLECTED", observed_at: null },
      expected_cpe_60_plus: { value: 310, raw_value: "310", unit: null, is_approximate: false, status: "COLLECTED", observed_at: null },
      profile_complete: true,
      pipeline_complete: true,
      data_updated_at: "2026-10-14T01:56:05Z",
      latest_snapshot_id: "44444444-4444-4444-8444-444444444444",
      collected_field_count: 11,
      failed_field_count: 0,
      field_sources: {},
      module_statuses: { basic: "COLLECTED" },
    };
    const snapshotPayload = {
      profile_complete: true,
      pipeline_complete: true,
      modules: {
        basic: {
          status: "COLLECTED",
          fields: [
            { field_key: "nickname", value: "甄选聊车", status: "COLLECTED" },
            { field_key: "creator_type_label", value: "汽车", status: "COLLECTED" },
            { field_key: "province", value: "内蒙古自治区", status: "COLLECTED" },
            { field_key: "city", value: "赤峰市", status: "COLLECTED" },
            { field_key: "industry_labels", value: ["金融业"], status: "COLLECTED" },
            { field_key: "introduction", value: "关注我", status: "COLLECTED" },
            { field_key: "gender", value: "1", status: "COLLECTED" },
            { field_key: "followers", value: { kind: "number", bound: "exact", amount: "1351784" }, raw_value: "1351784", status: "COLLECTED" },
            { field_key: "monthly_deep_users", value: { kind: "number", bound: "approximate", amount: "11580000" }, raw_value: "1,158w", is_approximate: true, status: "COLLECTED" },
          ],
        },
        spread: {
          status: "COLLECTED",
          fields: [
            { field_key: "interaction_rate", value: { kind: "structured", data: { value: 112 } }, raw_value: "112", status: "COLLECTED" },
            { field_key: "completion_rate", value: { kind: "structured", data: { value: 551 } }, raw_value: "551", status: "COLLECTED" },
            { field_key: "expected_cpm", value: { kind: "structured", data: { cpm_21_60: "2969", cpm_60: "3836" } }, raw_value: "{}", status: "COLLECTED" },
            { field_key: "expected_cpe", value: { kind: "structured", data: { cpe_21_60: "246", cpe_60: "310" } }, raw_value: "{}", status: "COLLECTED" },
          ],
        },
      },
    };
    const contents = { view_kind: "published", collection_type: "excellent_reach", status: "COMPLETE", cards: [] };
    // The detail page labels fields from the verified registry; the catalog carries no values.
    const fieldCatalog = {
      platform: "douyin_xingtu",
      contract_version: "test-contract",
      modules: [
        {
          key: "basic",
          fields: [
            { key: "nickname", name: "达人昵称", contract_name: "达人昵称", name_source: "contract", kind: "text", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "creator_type_label", name: "达人类型", contract_name: "达人类型", name_source: "contract", kind: "text", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "province", name: "省份", contract_name: "省份", name_source: "contract", kind: "text", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "city", name: "城市", contract_name: "城市", name_source: "contract", kind: "text", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "industry_labels", name: "行业标签", contract_name: "行业标签", name_source: "contract", kind: "tags", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "introduction", name: "介绍", contract_name: "介绍", name_source: "contract", kind: "text", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "followers", name: "粉丝数", contract_name: "粉丝数", name_source: "contract", kind: "number", unit: "count", period_label: null, empty_values: [], missing_source_status: null },
            { key: "monthly_deep_users", name: "月深度用户数", contract_name: "月深度用户数", name_source: "contract", kind: "number", unit: "count", period_label: "月", empty_values: [], missing_source_status: null },
          ],
        },
        {
          key: "spread",
          fields: [
            { key: "interaction_rate", name: "互动率及同行超越", contract_name: "互动率及同行超越", name_source: "contract", kind: "structured", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "completion_rate", name: "完播率及同行超越", contract_name: "完播率及同行超越", name_source: "contract", kind: "structured", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "expected_cpm", name: "预期 CPM", contract_name: "预期 CPM", name_source: "contract", kind: "structured", unit: null, period_label: null, empty_values: [], missing_source_status: null },
            { key: "expected_cpe", name: "预期 CPE", contract_name: "预期 CPE", name_source: "contract", kind: "structured", unit: null, period_label: null, empty_values: [], missing_source_status: null },
          ],
        },
      ],
    };
    const handler = (input: RequestInfo | URL) => {
      const path = String(input);
      requestedPaths.push(path);
      if (path === "/api/auth/me") return json(user);
      if (path === "/api/platforms/douyin_xingtu/profile-field-catalog") return json(fieldCatalog);
      if (path.startsWith("/api/creator-library/")) {
        if (path.endsWith("/history")) return json({ items: [], indexed_snapshots: 0, total_snapshots: 0 });
        if (path.endsWith("/quotes")) return json([
          {
            snapshot_id: "55555555-5555-4555-8555-555555555555",
            position: 0,
            cooperation_form: "植入视频",
            settlement_description: "固定价格",
            price_raw: 40000,
            origin_price_raw: 50000,
            observed_at: "2026-10-14T01:56:05Z",
            offer_raw: {},
          },
          {
            // 同一合作形式的**较早**观察 → 由 CD-04 起归入「报价历史」；当前报价取每个形式的最新一条。
            snapshot_id: "66666666-6666-4666-8666-666666666666",
            position: 1,
            cooperation_form: "植入视频",
            settlement_description: "固定价格",
            price_raw: 20000,
            origin_price_raw: null,
            observed_at: "2026-09-20T01:56:05Z",
            offer_raw: {},
          },
        ]);
        return json({ ...libraryCreator, profile_payload: snapshotPayload });
      }
      if (path.includes("/contents?")) return json(contents);
      if (path.includes(`/creators/${libraryCreator.creator_id}`)) return json({
        creator_id: libraryCreator.creator_id,
        platform_creator_id: libraryCreator.platform_creator_id,
        first_position: 0,
        view_kind: "published",
        snapshot_id: libraryCreator.latest_snapshot_id,
        observed_at: "2026-10-14T01:56:05Z",
        payload: snapshotPayload,
      });
      return json({}, 404);
    };

    // Entry B: the creator library is the presentation standard.
    vi.mocked(fetch).mockImplementation(handler);
    const library = renderApp(`/creators/${libraryCreator.creator_id}`);
    const libraryHeading = await screen.findByRole("heading", { name: "甄选聊车" });
    expect(libraryHeading).toBeInTheDocument();
    // Field labels come from the registry catalog request, which resolves after the profile itself.
    // CD-05 起默认章节是「商业能力」，概览面板不再挂载，因此改为核对默认章节的实际内容。
    const libraryFields = Array.from(document.querySelectorAll(".chapter-body .profile-facts dt")).map((node) => node.textContent);
    const libraryMetrics = Array.from(document.querySelectorAll(".rail-kpis span")).map((node) => node.textContent);
    const libraryChapters = Array.from(document.querySelectorAll(".chapter-tabs button")).map((node) => node.textContent);
    const libraryHeadings = Array.from(document.querySelectorAll(".chapter-body .profile-heading h3")).map((n) => n.textContent);
    expect(libraryHeadings).toEqual(["内容数据", "性价比/效果预估", "种草价值", "转化价值"]);
    // CD-03 需求 4.3: 月连接用户 → 月深度用户 → 粉丝 → 月涨粉率.
    expect(libraryMetrics).toEqual(["月连接用户", "月深度用户", "粉丝", "月涨粉率"]);
    // CD-05 任务一：移除「达人概览」，默认选中「商业能力」，最终五个 Tab。
    expect(libraryChapters).toEqual(["商业能力", "创作能力", "履约能力", "连接用户", "报价与历史"]);
    expect(document.querySelector(".chapter-tabs button.active")?.textContent).toBe("商业能力");
    expect(library.queryByRole("tab", { name: "达人概览" })).not.toBeInTheDocument();
    // CD-03 需求 4.2/4.6/4.11 and 4.1/4.7/4.8/4.10.
    expect(library.getByText("7503176021160493065")).toBeInTheDocument();
    expect(library.getAllByText("男").length).toBeGreaterThan(0);
    expect(library.getByText("关注我")).toBeInTheDocument();
    expect(library.queryByRole("button", { name: /^数据来源$/ })).not.toBeInTheDocument();
    const libraryRailFacts = Array.from(document.querySelectorAll(".rail-facts dt")).map((node) => node.textContent);
    expect(libraryRailFacts).toEqual(["性别", "地区", "MCN", "介绍"]);
    expect(document.querySelector(".identity-rail")?.textContent).not.toMatch(/采集完整|数据不完整|观测|完整性/);
    // 需求 4.10 — the drawer itself is retained, mounted outside the rail, and still opens.
    await userEvent.click(library.getByRole("button", { name: "字段来源" }));
    expect(await library.findByRole("dialog", { name: "数据质量与字段来源" })).toBeInTheDocument();
    await userEvent.click(library.getByRole("button", { name: "关闭数据来源" }));

    // CD-07：「报价与历史」章节保留报价历史，移除「系统采集历史」小模块。
    await userEvent.click(library.getByRole("tab", { name: "报价与历史" }));
    expect(await library.findByText("报价历史")).toBeInTheDocument();
    // 等报价数据真正返回（「20,000」只出现在该形式的较早观察里）。
    // 报价数据真正返回：同一形式的较早观察出现在报价历史列表中（该面板按平台原值输出，不加分隔符）。
    await waitFor(() => {
      expect(document.querySelector(".chapter-body")?.textContent).toContain("20000");
    });
    expect(library.queryByText("系统采集历史")).not.toBeInTheDocument();
    expect(document.querySelector(".history-list")).toBeNull();
    expect(document.querySelector(".history-panel")).toBeNull();
    // 该模块的取数消费已解除：页面不再请求 history 接口（接口与数据本身未删除）。
    expect(requestedPaths.some((path) => path.endsWith("/history"))).toBe(false);
    expect(requestedPaths.some((path) => path.endsWith("/quotes"))).toBe(true);
    library.unmount();

    // Entry A: task centric entry must render the same chapters and the same field labels, without
    // the library-only cooperation history chapter.
    vi.mocked(fetch).mockImplementation(handler);
    const fromTask = renderApp(`/tasks/${task.root_task_id}/creators/${libraryCreator.creator_id}`);
    expect(await screen.findByRole("heading", { name: "甄选聊车" })).toBeInTheDocument();
    const taskFields = Array.from(document.querySelectorAll(".chapter-body .profile-facts dt")).map((node) => node.textContent);
    const taskMetrics = Array.from(document.querySelectorAll(".rail-kpis span")).map((node) => node.textContent);
    const taskChapters = Array.from(document.querySelectorAll(".chapter-tabs button")).map((node) => node.textContent);
    const taskHeadings = Array.from(document.querySelectorAll(".chapter-body .profile-heading h3")).map((n) => n.textContent);
    // 任务入口与达人库入口默认章节内容一致（除达人库独有的报价与历史章节）。
    expect(taskHeadings).toEqual(libraryHeadings);
    expect(taskFields).toEqual(libraryFields);
    expect(taskMetrics).toEqual(libraryMetrics);
    expect(taskChapters).toEqual(["商业能力", "创作能力", "履约能力", "连接用户"]);
    expect(document.querySelector(".chapter-tabs button.active")?.textContent).toBe("商业能力");
    expect(fromTask.queryByRole("tab", { name: "达人概览" })).not.toBeInTheDocument();
    expect(fromTask.getByText("本任务采集快照")).toBeInTheDocument();
  });
});

describe("RETRY-01 retry scope", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  type Recorded = { path: string; init?: RequestInit };

  function mockDetail(overrides: Record<string, unknown>, calls: Recorded[] = []) {
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      calls.push({ path, init });
      if (path === "/api/auth/me") return json(user);
      if (path === `/api/tasks/${task.root_task_id}` && init?.method !== "POST") return json(overrides);
      if (path === `/api/tasks/${task.root_task_id}/retry` && init?.method === "POST") return json(overrides);
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
  }

  const continueDetail = {
    ...taskDetail,
    status: "PARTIAL_COMPLETED",
    stage: "部分完成",
    allowed_actions: ["retry", "cancel"],
    failure_reason: "PROFILE_SCOPE_INCOMPLETE",
    counts: { target_count: 100, discovered_count: 140, valid_count: 99, profile_complete_count: 19, featured_complete_count: 80, failed_count: 0 },
    retry_plan: {
      scope: "continue", remaining_to_target: 1, incomplete_valid_count: 80,
      retryable_creator_count: 80, search_exhausted: false,
      last_retry_at: null, changed_since_last_retry: null,
    },
  };

  const backfillDetail = {
    ...taskDetail,
    status: "PARTIAL_COMPLETED",
    stage: "部分完成",
    allowed_actions: ["retry", "cancel"],
    failure_reason: "PROFILE_SCOPE_INCOMPLETE",
    counts: { target_count: 100, discovered_count: 140, valid_count: 100, profile_complete_count: 20, featured_complete_count: 80, failed_count: 0 },
    retry_plan: {
      scope: "backfill", remaining_to_target: 0, incomplete_valid_count: 80,
      retryable_creator_count: 80, search_exhausted: true,
      last_retry_at: "2026-10-24T06:00:00Z", changed_since_last_retry: 2,
    },
  };

  it("offers 继续采集 with the remaining creator count", async () => {
    mockDetail(continueDetail);
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByRole("button", { name: /继续采集（还差 1 位）/ })).toBeInTheDocument();
    expect(screen.getByText(/只补数量，不会重新采集已入库达人/)).toBeInTheDocument();
    expect(screen.getByText(/待补采 80 位/)).toBeInTheDocument();
    expect(screen.getByText(/目标 100 · 还差 1 位/)).toBeInTheDocument();
  });

  it("offers 补采缺失字段 only for already-counted creators and shows the last retry", async () => {
    mockDetail(backfillDetail);
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByRole("button", { name: /补采缺失字段（80 位）/ })).toBeInTheDocument();
    expect(screen.getByText(/只补这些达人的缺失部分，不会新增达人/)).toBeInTheDocument();
    expect(screen.getByText("上次重试")).toBeInTheDocument();
    expect(screen.getByText(/更新了 2 位达人的资料/)).toBeInTheDocument();
  });

  it("falls back to 重试失败步骤 when the server sends no retry plan", async () => {
    mockDetail({ ...taskDetail, status: "FAILED", stage: "执行失败", allowed_actions: ["retry", "cancel"], failure_reason: "MODULE_COLLECTION_FAILED" });
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByRole("button", { name: /重试失败步骤/ })).toBeInTheDocument();
  });

  it("confirms the retry goal and does nothing when declined", async () => {
    const calls: Recorded[] = [];
    mockDetail(continueDetail, calls);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderApp(`/tasks/${task.root_task_id}`);
    const button = await screen.findByRole("button", { name: /继续采集（还差 1 位）/ });
    await userEvent.click(button);
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("只补足剩余 1 位有效达人"));
    expect(calls.filter((call) => call.path.endsWith("/retry"))).toHaveLength(0);
  });

  it("shows the actual failure reason alongside the retry scope", async () => {
    mockDetail({
      ...continueDetail,
      platform: "kuaishou_juxing",
      failure_reason: "PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED",
    });
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByText(/PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED/)).toBeInTheDocument();
    expect(screen.getByText(/只补数量，不会重新采集已入库达人/)).toBeInTheDocument();
  });

  it("shows the juxing child-account selection reminder with the exact account", async () => {
    mockDetail({
      ...taskDetail,
      platform: "kuaishou_juxing",
      status: "WAITING_FOR_ACCOUNT",
      stage: "等待选择子账号",
      allowed_actions: ["cancel"],
      failure_reason: "ACCOUNT_SELECTION_REQUIRED",
      challenge: {
        state: "DETECTED", challenge_type: "ACCOUNT_SELECTION",
        requires_user_action: true, monitoring: true,
        detected_count: 1, recovery_count: 0, waiting_seconds: 42,
        completed_creator_count: 0, remaining_creator_count: 22,
        delivered_result: "已保留 0 位达人及其已持久数据",
      },
      counts: { target_count: 22, discovered_count: 0, valid_count: 0, profile_complete_count: 0, featured_complete_count: 0, failed_count: 0 },
    });
    renderApp(`/tasks/${task.root_task_id}`);
    expect((await screen.findAllByText(/磁力聚星需要选择子账号/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/cpg果汁（60821564）/).length).toBeGreaterThan(0);
    expect(screen.getByText("子账号选择托管")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /前往执行单元接管浏览器/ })).toHaveAttribute("href", "/execution-units");
  });

  it("shows juxing followers, region, quote and content-type conditions on task detail", async () => {
    const juxingDetail = {
      ...taskDetail,
      platform: "kuaishou_juxing",
      keyword: "母婴",
      capability_version: "juxing-video-square-stage-c-v2",
      requirement: {
        schema_version: "requirement_form.v3", platform: "kuaishou_juxing", keyword: "母婴",
        content_types: ["maternal_child"], creator_types: [], followers: { min: 100000, max: 1000000, unit: "count" },
        creator_gender: null, creator_regions: [{ province_code: "11" }], creator_education: null,
        yellow_v_certification: null, connection_users: null, viewer_profile: null, fan_profile: null,
        quote: null, juxing_video_quotes: { seconds_1_20: null, seconds_21_60: { min: null, max: 10000, unit: "yuan" }, seconds_60_plus: null },
        sort_key: null, target_count: 10,
      },
      plan: null,
      counts: { target_count: 10, discovered_count: 20, valid_count: 10, profile_complete_count: 10, featured_complete_count: 0, failed_count: 0 },
      status: "COMPLETED", stage: "已完成", allowed_actions: [], failure_reason: null,
    };
    const base = { operators: [], options: [], dimensions: [], region_tree: [], incompatible_with: [], currencies: [], cooperation_forms: [] };
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path === `/api/tasks/${task.root_task_id}` && init?.method !== "POST") return json(juxingDetail);
      if (path === "/api/platforms/kuaishou_juxing/capabilities") return json({
        platform: "kuaishou_juxing", capability_version: "juxing-video-square-stage-c-v2",
        fields: [
          { ...base, field: "content_type", label: "内容类型", operators: ["in"], control: "single-select", options: [{ value: "maternal_child", label: "母婴亲子" }] },
          { ...base, field: "followers", label: "粉丝数量", operators: ["range"], control: "range", unit: "count", options: [{ value: "10w_100w", label: "10万-100万", range: { min: 100000, max: 1000000 } }] },
          { ...base, field: "region", label: "达人地域", operators: ["compound"], control: "cascader", region_tree: [{ value: "11", label: "北京", children: [{ value: "1101", label: "北京", children: [] }] }] },
          { ...base, field: "video_quote_1_20", label: "1-20秒视频报价", operators: ["range"], unit: "yuan", currencies: ["CNY"], cooperation_forms: ["short_video_1_20s"] },
          { ...base, field: "video_quote_21_60", label: "21-60秒视频报价", operators: ["range"], unit: "yuan", currencies: ["CNY"], cooperation_forms: ["short_video_21_60s"] },
          { ...base, field: "video_quote_60_plus", label: "60秒以上视频报价", operators: ["range"], unit: "yuan", currencies: ["CNY"], cooperation_forms: ["short_video_60s_plus"] },
        ],
        combinations: [], target_count_default: 3, target_count_min: 1, target_count_max: 30,
        fixed_sort_key: "platform_default", fixed_sort_label: "平台默认排序",
      });
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByText("内容类型")).toBeInTheDocument();
    expect(await screen.findByText("母婴亲子")).toBeInTheDocument();
    expect(screen.getByText("10万-100万")).toBeInTheDocument();
    expect(screen.getByText("北京")).toBeInTheDocument();
    expect(screen.getByText(/21-60秒视频/)).toBeInTheDocument();
  });
});

describe("RETRY-01 update tasks", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it("keeps the neutral retry wording for manual update batches", async () => {
    const updateDetail = {
      ...taskDetail,
      task_kind: "manual_update",
      status: "PARTIAL_COMPLETED",
      stage: "部分完成",
      allowed_actions: ["retry", "cancel"],
      failure_reason: "MODULE_COLLECTION_FAILED",
      update_targets: [],
      retry_plan: {
        scope: "backfill", remaining_to_target: 0, incomplete_valid_count: 1,
        retryable_creator_count: 1, search_exhausted: true,
        last_retry_at: null, changed_since_last_retry: null,
      },
    };
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      if (path === "/api/auth/me") return json(user);
      if (path === `/api/tasks/${task.root_task_id}` && init?.method !== "POST") return json(updateDetail);
      if (path.startsWith(`/api/tasks/${task.root_task_id}/creators`)) return json({ items: [], next_cursor: null });
      return json({}, 404);
    });
    renderApp(`/tasks/${task.root_task_id}`);
    expect(await screen.findByRole("button", { name: /重试失败步骤/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /补采缺失字段/ })).not.toBeInTheDocument();
  });
});


// --- KJX-01: juxing product pages ---------------------------------------------------------

const KJX_TASK_ID = "77777777-7777-4777-8777-777777777777";
const KJX_CREATOR_ID = "88888888-8888-4888-8888-888888888888";

const juxingMetric = (value: string | null) => ({
  value,
  raw_value: value,
  unit: value === null ? null : "count",
  is_approximate: false,
  status: value === null ? "NO_DATA" : "COLLECTED",
  observed_at: null,
});

const juxingCatalog = {
  platform: "kuaishou_juxing" as const,
  contract_version: "juxing-test",
  modules: [
    {
      key: "basic",
      fields: [
        { key: "nickname", name: "昵称", contract_name: "昵称", name_source: "contract" as const, kind: "text", unit: null, period_label: null, empty_values: [], missing_source_status: null },
        { key: "content_type_labels", name: "内容类型", contract_name: "内容类型", name_source: "contract" as const, kind: "tags", unit: null, period_label: null, empty_values: [], missing_source_status: null },
        { key: "followers", name: "粉丝数", contract_name: "粉丝数", name_source: "contract" as const, kind: "number", unit: "count", period_label: null, empty_values: [], missing_source_status: null },
        { key: "cooperation_offers", name: "视频报价", contract_name: "视频报价", name_source: "contract" as const, kind: "structured", unit: null, period_label: null, empty_values: [], missing_source_status: null },
      ],
    },
    { key: "spread", fields: [
      { key: "play_median", name: "播放量中位数", contract_name: "播放量中位数", name_source: "contract" as const, kind: "number", unit: "count", period_label: null, empty_values: [], missing_source_status: null },
    ] },
    { key: "works", fields: [
      { key: "works", name: "代表及近期作品", contract_name: "代表及近期作品", name_source: "contract" as const, kind: "structured", unit: null, period_label: null, empty_values: [], missing_source_status: null },
    ] },
    { key: "audience", fields: [
      { key: "fan_portrait", name: "粉丝画像", contract_name: "粉丝画像", name_source: "contract" as const, kind: "structured", unit: null, period_label: null, empty_values: [], missing_source_status: null },
      { key: "viewer_portrait", name: "观众画像", contract_name: "观众画像", name_source: "contract" as const, kind: "structured", unit: null, period_label: null, empty_values: [], missing_source_status: null },
    ] },
  ],
};

const juxingCreatorPayload = {
  modules: {
    basic: {
      status: "COLLECTED",
      fields: [
        { field_key: "nickname", value: "聚星同名达人", status: "COLLECTED" },
        { field_key: "content_type_labels", value: ["母婴亲子"], status: "COLLECTED" },
        { field_key: "followers", value: { kind: "number", amount: "21686076", bound: "exact" }, status: "COLLECTED", unit: "count" },
        {
          field_key: "cooperation_offers",
          status: "COLLECTED",
          value: { kind: "structured", data: [{ duration: "1-20秒", platform_price_raw: 20000, price_yuan: 20, currency: "CNY" }] },
        },
      ],
    },
    spread: {
      status: "COLLECTED",
      fields: [{ field_key: "play_median", value: { kind: "number", amount: "13092269", bound: "exact" }, status: "COLLECTED", unit: "count" }],
    },
    works: {
      status: "COLLECTED",
      fields: [{ field_key: "works", value: { kind: "structured", data: [{ platform_content_id: "w1", title: "合成作品", play_count: 100 }] }, status: "COLLECTED" }],
    },
    audience: {
      status: "COLLECTED",
      fields: [{ field_key: "fan_portrait", value: { kind: "structured", data: { gender: { male: 0.4 } } }, status: "COLLECTED", period_label: "近30天" }],
    },
  },
  profile_complete: true,
  pipeline_complete: true,
};

const juxingLibrarySummary = {
  creator_id: KJX_CREATOR_ID,
  platform: "kuaishou_juxing" as const,
  platform_creator_id: "578000000001",
  display_name: "聚星同名达人",
  avatar_uri: null,
  creator_type_label: null,
  province: "广东省",
  city: "深圳市",
  industry_labels: [],
  content_theme_labels: ["母婴亲子"],
  followers: juxingMetric("21686076"),
  monthly_deep_users: juxingMetric(null),
  monthly_connected_users: juxingMetric(null),
  monthly_follower_growth_rate: juxingMetric("0.0125"),
  interaction_rate: juxingMetric("0.03911"),
  completion_rate: juxingMetric("0.22881"),
  play_median: juxingMetric("13092269"),
  average_duration: juxingMetric("10.476"),
  average_likes: juxingMetric("2"),
  average_comments: juxingMetric(null),
  average_shares: juxingMetric(null),
  expected_cpm_21_60: juxingMetric(null),
  expected_cpm_60_plus: juxingMetric(null),
  expected_cpe_21_60: juxingMetric(null),
  expected_cpe_60_plus: juxingMetric(null),
  profile_complete: true,
  pipeline_complete: true,
  data_updated_at: "2026-10-27T20:00:00+08:00",
};

const juxingLibraryDetail = {
  ...juxingLibrarySummary,
  latest_snapshot_id: "99999999-9999-4999-8999-999999999999",
  mcn_name: "合成 MCN",
  introduction: "合成简介",
  gender: null,
  collected_field_count: 6,
  failed_field_count: 0,
  field_sources: {},
  module_statuses: { basic: "COLLECTED", spread: "COLLECTED", works: "COLLECTED", audience: "COLLECTED" },
  profile_payload: juxingCreatorPayload,
};

const juxingTask = {
  root_task_id: KJX_TASK_ID,
  platform: "kuaishou_juxing" as const,
  status: "COMPLETED",
  stage: "已完成",
  version: 5,
  created_at: "2026-10-27T20:00:00Z",
  updated_at: "2026-10-27T20:10:00Z",
  completed_at: "2026-10-27T20:10:00Z",
  created_by: "user-a",
  created_by_name: "媒介 A",
  source: "product" as const,
  keyword: "母婴",
  counts: { target_count: 1, discovered_count: 1, valid_count: 1, profile_complete_count: 1, featured_complete_count: 0, failed_count: 0 },
  allowed_actions: [],
  failure_reason: null,
};

const juxingTaskDetail = {
  ...juxingTask,
  task_kind: "collection" as const,
  requirement: { schema_version: "requirement_form.v3", platform: "kuaishou_juxing", keyword: "母婴", content_types: ["maternal_child"], creator_types: [], followers: null, creator_gender: null, creator_regions: [], creator_education: null, yellow_v_certification: null, connection_users: null, viewer_profile: null, fan_profile: null, quote: null, juxing_video_quotes: null, sort_key: null, target_count: 1 },
  capability_version: "juxing-video-square-stage-b-v1",
  plan: null,
  field_errors: [],
  origin_root_task_id: null,
  challenge: null,
  intake: null,
  update_targets: [],
  retry_plan: null,
};

const juxingCreatorSummary = {
  creator_id: KJX_CREATOR_ID,
  platform: "kuaishou_juxing" as const,
  platform_creator_id: "578000000001",
  first_position: 0,
  view_kind: "published" as const,
  snapshot_id: "99999999-9999-4999-8999-999999999999",
  observed_at: "2026-10-27T20:00:00+08:00",
  payload: juxingCreatorPayload,
};

function mockJuxingApi(overrides: Record<string, unknown> = {}) {
  vi.mocked(fetch).mockImplementation((input) => {
    const path = String(input);
    if (path === "/api/auth/me") return json(user);
    if (path === "/api/platforms/kuaishou_juxing/profile-field-catalog") return json(juxingCatalog);
    if (path.startsWith("/api/creator-library?")) {
      return json({ items: [juxingLibrarySummary], next_cursor: null });
    }
    if (path === `/api/creator-library/${KJX_CREATOR_ID}`) return json(juxingLibraryDetail);
    if (path === `/api/tasks/${KJX_TASK_ID}`) return json(juxingTaskDetail);
    if (path.startsWith(`/api/tasks/${KJX_TASK_ID}/creators?`)) {
      return json({ items: [juxingCreatorSummary], next_cursor: null });
    }
    if (path === `/api/tasks/${KJX_TASK_ID}/creators/${KJX_CREATOR_ID}`) return json(juxingCreatorSummary);
    if (path in overrides) return json(overrides[path]);
    return json({}, 404);
  });
}

describe("KJX-01 juxing product pages", () => {
  beforeEach(() => { vi.stubGlobal("fetch", vi.fn()); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("lists juxing creators under the platform filter and drops Xingtu-only filters", async () => {
    mockJuxingApi();
    renderApp("/creators?platform=kuaishou_juxing");
    expect(await screen.findByText("磁力聚星达人")).toBeInTheDocument();
    expect(await screen.findByText("聚星同名达人")).toBeInTheDocument();
    expect(screen.getByText(/磁力聚星 · 广东省/)).toBeInTheDocument();
    expect(screen.getByText("月涨粉率")).toBeInTheDocument();
    expect(screen.getByText("1.25%")).toBeInTheDocument();
    expect(screen.queryByLabelText("按行业筛选")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("按合作形式筛选")).not.toBeInTheDocument();
    const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.includes("platform=kuaishou_juxing"))).toBe(true);

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("达人库平台"), "douyin_xingtu");
    await waitFor(() => {
      const nextUrls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
      expect(nextUrls.some((url) => url.includes("/api/creator-library?") && !url.includes("platform="))).toBe(true);
    });
    expect(await screen.findByLabelText("按行业筛选")).toBeInTheDocument();
  });

  it("renders a juxing library detail and never requests Xingtu-only sub-resources", async () => {
    mockJuxingApi();
    renderApp(`/creators/${KJX_CREATOR_ID}`);
    expect(await screen.findByText("快手ID")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "基础资料" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "传播表现" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "商业能力" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /手动更新/ })).not.toBeInTheDocument();
    await waitFor(() => {
      const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url.includes(`/api/creator-library/${KJX_CREATOR_ID}/quotes`))).toBe(false);
      expect(urls.some((url) => url.includes(`/api/creator-library/${KJX_CREATOR_ID}/update`))).toBe(false);
      expect(urls.some((url) => url.includes(`/api/creator-library/${KJX_CREATOR_ID}/contents`))).toBe(false);
      expect(urls.some((url) => url.includes(`/api/creator-library/${KJX_CREATOR_ID}/videos`))).toBe(false);
    });
  });

  it("shows juxing task counts without the F06 card and uses platform-aware copy", async () => {
    mockJuxingApi();
    renderApp(`/tasks/${KJX_TASK_ID}`);
    expect(await screen.findByText("磁力聚星")).toBeInTheDocument();
    expect(screen.queryByText("精选完整")).not.toBeInTheDocument();
    expect(screen.queryByText("F06 双集合")).not.toBeInTheDocument();
    expect(screen.queryByText(/正在星图中/)).not.toBeInTheDocument();
    expect(await screen.findByText("聚星同名达人")).toBeInTheDocument();
    expect(screen.getByText(/快手ID 578000000001/)).toBeInTheDocument();
  });

  it("renders a juxing task creator detail from the task snapshot without Xingtu requests", async () => {
    mockJuxingApi();
    renderApp(`/tasks/${KJX_TASK_ID}/creators/${KJX_CREATOR_ID}`);
    expect(await screen.findByText("快手ID")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "代表作品" })).toBeInTheDocument();
    await waitFor(() => {
      const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url.includes("/contents"))).toBe(false);
      expect(urls.some((url) => url.includes("/videos"))).toBe(false);
    });
  });
});
