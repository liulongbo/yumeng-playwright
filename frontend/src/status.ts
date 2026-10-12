import type { TaskStatus } from "./types";

export const terminalStatuses = new Set<TaskStatus>([
  "CANCELLED", "COMPLETED", "PARTIAL_COMPLETED", "FAILED_VALIDATION", "FAILED",
]);

export const waitingStatuses = new Set<TaskStatus>([
  "RETRY_WAIT", "WAITING_FOR_LOGIN", "WAITING_FOR_ACCOUNT", "WAITING_FOR_VERIFICATION",
  "WAITING_FOR_RESOURCE", "PAUSED_BUDGET",
]);

export const statusLabel: Record<TaskStatus, string> = {
  RECEIVED: "已接收", PARSING: "需求转换", QUEUED: "排队中", SEARCHING: "发现达人",
  COLLECTING: "采集中", PERSISTING: "发布快照", RETRY_WAIT: "等待重试",
  WAITING_FOR_LOGIN: "等待平台登录", WAITING_FOR_ACCOUNT: "等待正确账号",
  WAITING_FOR_VERIFICATION: "等待安全验证",
  WAITING_FOR_RESOURCE: "等待执行资源", PAUSED_BUDGET: "预算暂停", CANCELLING: "取消中",
  CANCELLED: "已取消", COMPLETED: "已完成", PARTIAL_COMPLETED: "部分完成",
  FAILED_VALIDATION: "需求校验失败", FAILED: "执行失败",
};

export function statusTone(status: TaskStatus) {
  if (status === "COMPLETED") return "success";
  if (["FAILED", "FAILED_VALIDATION"].includes(status)) return "danger";
  // A user-initiated cancellation is a delivered command, not a fault: keep it visually neutral so
  // it is not read as a system failure (FIX-01 P3-D).
  if (status === "CANCELLED") return "neutral";
  if (["PARTIAL_COMPLETED", "PAUSED_BUDGET", "WAITING_FOR_LOGIN", "WAITING_FOR_ACCOUNT", "WAITING_FOR_VERIFICATION"].includes(status)) return "warning";
  if (["RECEIVED", "PARSING", "QUEUED", "SEARCHING", "COLLECTING", "PERSISTING", "CANCELLING"].includes(status)) return "active";
  return "neutral";
}

export function formatDate(value?: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(value));
}

export function shortId(value: string) { return value.slice(0, 8); }
