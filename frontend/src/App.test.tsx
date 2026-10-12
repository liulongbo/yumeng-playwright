import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
  afterEach(() => { vi.restoreAllMocks(); });

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
    expect(screen.queryByText("达人类型")).not.toBeInTheDocument();
    await userEvent.type(keyword, "宠物");
    await userEvent.click(screen.getByRole("button", { name: /提交采集任务/ }));
    await waitFor(() => expect(calls.some((call) => call.path === "/api/tasks" && call.init?.method === "POST")).toBe(true));
    const create = calls.find((call) => call.path === "/api/tasks" && call.init?.method === "POST")!;
    expect(new Headers(create.init?.headers).get("Idempotency-Key")).toBe("00000000-0000-4000-8000-000000000001");
    expect(JSON.parse(String(create.init?.body))).toMatchObject({ keyword: "宠物", target_count: 20 });
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
    expect(await screen.findByText("等待安全验证")).toBeInTheDocument();
    expect(await screen.findByText("安全验证托管")).toBeInTheDocument();
    expect(screen.getAllByText("等待处理").length).toBeGreaterThan(0);
    expect(screen.getByText("当前达人 creator-1")).toBeInTheDocument();
    expect(screen.getByText("已保留 8 位达人及其已持久数据")).toBeInTheDocument();
  });
});
