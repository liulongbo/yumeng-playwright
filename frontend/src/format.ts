/**
 * Display formatting for platform-native creator values.
 *
 * Rules (see docs/tasks/CD-02.md, docs/tasks/CD-03.md):
 * - Counts use thousands separators; an approximate platform value keeps a leading `≈`.
 * - The creator-profile rail counts render in 万/k (`countUnitText`); every other count group stays
 *   the platform's own number with a thousands separator (`countText`).
 * - Only a field the verified contract registers as `kind: "ratio"` is scaled to a percentage.
 *   Everything else keeps the platform's own number, unit-less and un-scaled.
 * - A platform "present but empty" marker (`-`, `--`, `—`, `""`, `{}`, `[]`) is an empty state,
 *   never a zero.  A real `0` stays `0`.
 */

// A platform "present but empty" marker.  `[]`/`{}` also arrive as literal strings inside a
// structured leaf (`basic.content_style_labels_raw` was observed as the text `"[]"`).
const EMPTY_TOKENS = new Set(["", "-", "--", "—", "－", "n/a", "null", "undefined", "[]", "{}"]);

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** True when a value carries no information: a dash marker, empty string, empty list or empty object. */
export function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return EMPTY_TOKENS.has(value.trim().toLowerCase());
  if (Array.isArray(value)) return value.length === 0;
  const item = record(value);
  if (!item) return false;
  if ("data" in item) return isBlank(item.data);
  if ("value" in item) return isBlank(item.value);
  if ("amount" in item) return isBlank(item.amount);
  return Object.keys(item).length === 0;
}

/** Platform numbers arrive as strings, sometimes with separators; `null` means "not a number". */
export function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return null;
  const text = typeof value === "string" ? value.replace(/,/g, "").trim() : value;
  const amount = Number(text);
  return Number.isFinite(amount) ? amount : null;
}

/** Counts and other un-scaled platform numbers, thousands separated. */
export function countText(value: unknown, options: { approximate?: boolean } = {}): string {
  const amount = numberOrNull(value);
  if (amount === null) return "—";
  const text = amount.toLocaleString("zh-CN");
  return options.approximate ? `≈${text}` : text;
}

/** Group the integer part of an already-truncated fixed-point text; keep its fraction as written. */
function groupFixed(text: string, fractionDigits: number): string {
  const [whole, fraction] = text.split(".");
  const grouped = Number(whole).toLocaleString("zh-CN");
  return fractionDigits > 0 && fraction !== undefined ? `${grouped}.${fraction}` : grouped;
}

/**
 * A platform creator-profile count in the unit the platform itself uses (CD-03 需求 4.4).
 *
 * The three rail metrics are the **same quantity at different scales**: 巨量星图 renders
 * `月连接用户数` as `2,376.6w` and `粉丝` as `135.2w` — both are `万` (10,000).  The stored value stays
 * the raw head-count (`1351784`); only this display layer scales it, and the exact figure remains
 * reachable through the metric's `raw_value`.  Tiers, confirmed by the user on 2026-10-15:
 *
 * - `n >= 10,000`      → `135.2万`  (one decimal, rounded — `1,351,784` is `135.2万`, matching the
 *                        platform's own `135.2w`)
 * - `1,000 <= n < 10,000` → `7.5k`
 * - `n < 1,000`        → the plain number (`999`)
 *
 * `≈` is kept for a value the platform itself marked approximate (an exact reading is not implied).
 */
export function countUnitText(value: unknown, options: { approximate?: boolean } = {}): string {
  const amount = numberOrNull(value);
  if (amount === null) return "—";
  const approximate = options.approximate === true;
  const negative = amount < 0;
  const magnitude = Math.abs(amount);
  let text: string;
  if (magnitude >= 10_000) {
    // `toFixed` keeps one decimal: 23,439,854 → `2,344.0万`, 1,351,784 → `135.2万`.
    text = `${groupFixed((magnitude / 10_000).toFixed(1), 1)}万`;
  } else if (magnitude >= 1_000) {
    text = `${groupFixed((magnitude / 1_000).toFixed(1), 1)}k`;
  } else {
    text = magnitude.toLocaleString("zh-CN");
  }
  return `${negative ? "-" : ""}${approximate ? "≈" : ""}${text}`;
}

/**
 * A count in the unit the creator-detail business chapters use (CD-04 需求 4.1/4.2, user-confirmed
 * 2026-10-15).  Same family as `countUnitText`, but the top tier is spelled `w` — the form the
 * platform and the reference page use inside these chapters (`5.4w`, `1.1w`, `2.4w`).
 *
 * - `n >= 10,000`        → `93.0w`   (one decimal, rounded)
 * - `1,000 <= n < 10,000` → `3.0k`
 * - `n < 1,000`          → the plain number (`999`)
 *
 * `≈` is kept for a platform-approximate value.  Only the display layer scales; the stored
 * head-count is untouched, and `countUnitText` (the identity rail's `万` form) keeps its own rule.
 */
export function countWanText(value: unknown, options: { approximate?: boolean } = {}): string {
  const amount = numberOrNull(value);
  if (amount === null) return "—";
  const approximate = options.approximate === true;
  const negative = amount < 0;
  const magnitude = Math.abs(amount);
  let text: string;
  if (magnitude >= 10_000) {
    text = `${groupFixed((magnitude / 10_000).toFixed(1), 1)}w`;
  } else if (magnitude >= 1_000) {
    text = `${groupFixed((magnitude / 1_000).toFixed(1), 1)}k`;
  } else {
    text = magnitude.toLocaleString("zh-CN");
  }
  return `${negative ? "-" : ""}${approximate ? "≈" : ""}${text}`;
}

/**
 * A platform `overtake` reading as the percentile it really is.
 *
 * Measured and confirmed against the live 巨量星图 page (CD-02, 2026-10-14): the stored integer is a
 * 万分比 (`7493` → `74.93%`, `9801` → `98.01%`), and the platform renders it as
 * 「**优于**同类型达人 X%」—— never as a "低于" (below) share.  One decimal, rounded.
 */
export function overtakePercentText(value: unknown): string {
  const amount = numberOrNull(value);
  if (amount === null) return "—";
  return `${(amount / 100).toFixed(1)}%`;
}

/**
 * A registered `ratio` decimal (for example `0.01969004266000137`) shown as a percentage.
 * The platform itself renders this field as a percent (巨量星图 达人详情「月涨粉率」).
 */
export function ratioPercentText(value: unknown): string {
  const amount = numberOrNull(value);
  if (amount === null) return "—";
  return `${(amount * 100).toFixed(2)}%`;
}

/** A platform percent-like integer such as `fans_growth_rate` (万分比): shown as its percent value. */
export function tenThousandthsPercentText(value: unknown): string {
  const amount = numberOrNull(value);
  if (amount === null) return "—";
  return `${(amount / 100).toFixed(2)}%`;
}

/** Unix seconds as a platform sent them (`audience_last_updated_at`, `create_time`). */
export function unixSecondsText(value: unknown): string {
  const seconds = numberOrNull(value);
  if (seconds === null || seconds <= 0) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour12: false,
  }).format(new Date(seconds * 1000));
}

/** A `YYYY-MM-DD` platform date, or an ISO timestamp, shown as a plain date. */
export function plainDateText(value: unknown): string {
  if (typeof value !== "string" || isBlank(value)) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour12: false,
  }).format(parsed);
}

/**
 * Some platform fields return a JSON document *inside* a string leaf, for example
 * `fulfillment.industry_order_distribution` → `"[{\"key\":\"1916\",\"rate\":\"1.0\"}]"`.
 * Only a successfully parsed array/object is returned; anything else keeps its text form.
 */
export function parseEmbeddedJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (!text.startsWith("[") && !text.startsWith("{")) return value;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return value;
  }
}

/** A platform range string such as `20,000 - 100,000` or `0.5% - 1%`. */
export function rangeText(value: unknown): string {
  if (typeof value !== "string") return "—";
  return isBlank(value) ? "—" : value;
}

/** Truncated plain text with the full value exposed through `title`. */
export function shortText(value: unknown, max = 48): string {
  if (typeof value !== "string" || isBlank(value)) return "—";
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

export const fieldStatusLabel: Record<string, string> = {
  COLLECTED: "已采集",
  NO_DATA: "平台暂无数据",
  NOT_ATTEMPTED: "本次未采集",
  NOT_PROVIDED: "平台未提供",
  NO_PERMISSION: "无访问权限",
  FAILED: "采集失败",
  MISSING_SOURCE: "未取到对应响应",
};

export function fieldStatusText(status: unknown): string {
  const key = String(status ?? "");
  return fieldStatusLabel[key] ?? "暂无数据";
}

export function moduleStatusTone(status: unknown): "ok" | "warn" | "bad" {
  const key = String(status ?? "");
  if (key === "COLLECTED") return "ok";
  if (key === "FAILED" || key === "NO_PERMISSION") return "bad";
  return "warn";
}
