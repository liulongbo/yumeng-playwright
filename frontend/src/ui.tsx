import type { ReactNode } from "react";
import { AlertTriangle, Inbox, LoaderCircle, RefreshCcw } from "lucide-react";
import { ApiError } from "./api";
import type { TaskStatus } from "./types";
import { statusLabel, statusTone } from "./status";

export function BrandMark() {
  return <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>;
}

export function StatusBadge({ status, pulse = false }: { status: TaskStatus; pulse?: boolean }) {
  return <span className={`status-badge ${statusTone(status)} ${pulse ? "pulse" : ""}`}>
    <span className="status-dot" />{statusLabel[status]}
  </span>;
}

export function PageHeader({ eyebrow, title, description, actions }: {
  eyebrow?: string; title: string; description?: string; actions?: ReactNode;
}) {
  return <header className="page-header">
    <div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{description && <p>{description}</p>}</div>
    {actions && <div className="header-actions">{actions}</div>}
  </header>;
}

export function LoadingState({ label = "正在加载数据" }: { label?: string }) {
  return <div className="state-panel"><LoaderCircle className="spin" /><strong>{label}</strong><span>请稍候，页面会自动更新。</span></div>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="state-panel"><Inbox /><strong>{title}</strong><span>{description}</span>{action}</div>;
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError ? error.detail.message : "暂时无法读取数据";
  const requestId = error instanceof ApiError ? error.detail.request_id : null;
  return <div className="state-panel danger-state"><AlertTriangle /><strong>{message}</strong>
    <span>{requestId ? `请求编号 ${requestId}` : "请检查网络后重试。"}</span>
    {retry && <button className="button secondary" onClick={retry}><RefreshCcw size={16} />重新加载</button>}
  </div>;
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return <div className="skeleton-list" aria-label="加载中">{Array.from({ length: rows }, (_, i) => <div className="skeleton-row" key={i} />)}</div>;
}
