import type {
  Capabilities, ContentPage, CreatorPage, CreatorSummary, ProductError,
  RequirementForm, TaskDetail, TaskPage, UserView,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public detail: ProductError) {
    super(detail.message || detail.code);
  }
}

let csrfToken = "";

export function setCsrfToken(value: string) { csrfToken = value; }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.method && init.method !== "GET" && init.method !== "HEAD" && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, { ...init, headers, credentials: "include" });
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("xingtu:auth-expired"));
    throw new ApiError(response.status, body as ProductError);
  }
  return body as T;
}

export const api = {
  me: () => request<UserView>("/api/auth/me"),
  login: (username: string, password: string) => request<UserView>("/api/auth/login", {
    method: "POST", body: JSON.stringify({ username, password }),
  }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  capabilities: () => request<Capabilities>("/api/platforms/douyin_xingtu/capabilities"),
  listTasks: (params: URLSearchParams) => request<TaskPage>(`/api/tasks?${params.toString()}`),
  task: (id: string) => request<TaskDetail>(`/api/tasks/${id}`),
  createTask: (form: RequirementForm, idempotencyKey: string, origin?: string | null) =>
    request<{ root_task_id: string; status: "RECEIVED" }>("/api/tasks", {
      method: "POST",
      headers: {
        "Idempotency-Key": idempotencyKey,
        ...(origin ? { "X-Origin-Root-Task-Id": origin } : {}),
      },
      body: JSON.stringify(form),
    }),
  command: (id: string, action: "cancel" | "continue" | "retry", version: number, idempotencyKey: string) =>
    request<TaskDetail>(`/api/tasks/${id}/${action}`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ expected_version: version }),
    }),
  creators: (id: string, cursor?: string | null) => request<CreatorPage>(
    `/api/tasks/${id}/creators?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  ),
  creator: (taskId: string, creatorId: string) => request<CreatorSummary>(
    `/api/tasks/${taskId}/creators/${creatorId}`,
  ),
  contents: (taskId: string, creatorId: string, type: "excellent_reach" | "excellent_seeding", cursor?: string | null) =>
    request<ContentPage>(
      `/api/tasks/${taskId}/creators/${creatorId}/contents?collection_type=${type}&limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),
};
