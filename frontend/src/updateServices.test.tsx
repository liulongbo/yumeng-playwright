import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UpdateServicesPage } from "./updateServices";

const rootVideo = "11111111-1111-4111-8111-111111111111";
const rootLive = "22222222-2222-4222-8222-222222222222";

const page = {
  scheduler_alive: false,
  scheduler_last_tick_at: null,
  scheduler_tick_seconds: 60,
  items: [
    {
      platform: "douyin_xingtu",
      creator_scene: "video_square",
      enabled: true,
      effective_enabled: false,
      scheduler_alive: false,
      scheduler_last_tick_at: null,
      registry_available: true,
      unavailable_reason: "SCHEDULER_NOT_RUNNING",
      enrolled_count: 12,
      due_count: 4,
      in_flight_count: 0,
      missing_target_count: 0,
      next_due_at: "2026-11-06T10:00:00Z",
      last_attempt_at: "2026-11-05T09:00:00Z",
      last_success_at: "2026-11-05T09:10:00Z",
      last_task: {
        root_task_id: rootVideo,
        state: "PARTIAL_COMPLETED",
        stage: "采集达人资料",
        created_at: "2026-11-05T09:00:00Z",
        completed_at: "2026-11-05T09:10:00Z",
        failure_reason: "MODULE_COLLECTION_FAILED",
        target_count: 3,
        valid_count: 2,
        profile_complete_count: 1,
      },
    },
    {
      platform: "douyin_xingtu",
      creator_scene: "live_square",
      enabled: false,
      effective_enabled: false,
      scheduler_alive: false,
      scheduler_last_tick_at: null,
      registry_available: true,
      unavailable_reason: null,
      enrolled_count: 0,
      due_count: 0,
      in_flight_count: 0,
      missing_target_count: 0,
      next_due_at: null,
      last_attempt_at: null,
      last_success_at: null,
      last_task: null,
    },
    {
      platform: "kuaishou_juxing",
      creator_scene: "video_square",
      enabled: false,
      effective_enabled: false,
      scheduler_alive: false,
      scheduler_last_tick_at: null,
      registry_available: false,
      unavailable_reason: "UPDATE_VIDEO_REGISTRY_UNAVAILABLE",
      enrolled_count: 0,
      due_count: 0,
      in_flight_count: 0,
      missing_target_count: 2,
      next_due_at: null,
      last_attempt_at: null,
      last_success_at: null,
      last_task: {
        root_task_id: rootLive,
        state: "CANCELLED",
        stage: "已取消",
        created_at: "2026-11-04T09:00:00Z",
        completed_at: "2026-11-04T09:01:00Z",
        failure_reason: null,
        target_count: 1,
        valid_count: 0,
        profile_complete_count: 0,
      },
    },
    {
      platform: "kuaishou_juxing",
      creator_scene: "live_square",
      enabled: false,
      effective_enabled: false,
      scheduler_alive: false,
      scheduler_last_tick_at: null,
      registry_available: true,
      unavailable_reason: null,
      enrolled_count: 0,
      due_count: 0,
      in_flight_count: 0,
      missing_target_count: 0,
      next_due_at: null,
      last_attempt_at: null,
      last_success_at: null,
      last_task: null,
    },
  ],
};

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/settings"]}><UpdateServicesPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("scheduled update services page", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders the four platform/scene groups and the offline scheduler state", async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      if (String(input) === "/api/update-services") return json(page);
      return json({}, 404);
    });
    renderPage();
    expect(await screen.findByRole("heading", { name: "自动更新服务" })).toBeInTheDocument();
    expect(screen.getAllByText("调度器未运行").length).toBeGreaterThan(0);
    expect(screen.getAllByText("巨量星图")).toHaveLength(2);
    expect(screen.getAllByText("磁力聚星")).toHaveLength(2);
    expect(screen.getAllByText("短视频广场")).toHaveLength(2);
    expect(screen.getAllByText("直播广场")).toHaveLength(2);
    expect(screen.getAllByRole("switch")).toHaveLength(4);
    expect(screen.getByRole("switch", { name: /关闭 巨量星图短视频广场自动更新/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByText("等待调度器")).toBeInTheDocument();
    expect(screen.getByText("2 位缺少详情定位，暂未纳入")).toBeInTheDocument();
    expect(screen.getByText("平台短视频契约不可用")).toBeInTheDocument();
  });

  it("persists a switch through PUT and refreshes the page", async () => {
    let putDone = false;
    const updated = {
      ...page.items[1],
      enabled: true,
      unavailable_reason: "SCHEDULER_NOT_RUNNING",
    };
    const requests: Array<{ input: string; init?: RequestInit }> = [];
    vi.mocked(fetch).mockImplementation((input, init) => {
      requests.push({ input: String(input), init });
      if (String(input) === "/api/update-services" && (!init || init.method === undefined)) {
        const live = putDone ? updated : page.items[1];
        return json({ ...page, items: [page.items[0], live, page.items[2], page.items[3]] });
      }
      if (String(input) === "/api/update-services/douyin_xingtu/live_square") {
        putDone = true;
        return json(updated);
      }
      return json({}, 404);
    });
    renderPage();
    const toggle = await screen.findByRole("switch", {
      name: /开启 巨量星图直播广场自动更新/,
    });
    await userEvent.click(toggle);
    await waitFor(() => {
      const put = requests.find((request) => request.init?.method === "PUT");
      expect(put).toBeTruthy();
      expect(put?.input).toBe("/api/update-services/douyin_xingtu/live_square");
      expect(JSON.parse(String(put?.init?.body))).toEqual({ enabled: true });
    });
    await waitFor(() => {
      expect(screen.getByRole("switch", { name: /关闭 巨量星图直播广场自动更新/ })).toHaveAttribute(
        "aria-checked",
        "true",
      );
    });
  });

  it("links the latest scheduled batch and shows its result without inventing counts", async () => {
    vi.mocked(fetch).mockImplementation((input) => {
      if (String(input) === "/api/update-services") return json(page);
      return json({}, 404);
    });
    renderPage();
    const link = await screen.findByRole("link", { name: /11111111/ });
    expect(link).toHaveAttribute("href", `/tasks/${rootVideo}`);
    expect(screen.getByText(/部分完成 · 2\/3 位 · 完整 1/)).toBeInTheDocument();
    expect(screen.getByText("MODULE_COLLECTION_FAILED")).toBeInTheDocument();
  });

  it("shows a retryable error state when the read model is unavailable", async () => {
    vi.mocked(fetch).mockImplementation(() =>
      json({ code: "STORAGE_UNAVAILABLE", message: "暂时无法读取数据" }, 503),
    );
    renderPage();
    expect(await screen.findByText("暂时无法读取数据")).toBeInTheDocument();
  });
});
