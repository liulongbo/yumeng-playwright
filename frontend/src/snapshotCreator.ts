/**
 * Adapts one task-scoped creator snapshot into the same shape the creator library uses, so the task
 * entry and the library entry can render identical fields through one set of components.
 *
 * Source of truth is the immutable snapshot payload (`modules.<module>.fields[]`). Field keys and
 * value shapes below are exactly the ones the library read-model backfill reads from the same
 * payload (`migrations/010_creator_library.sql`, `backend/src/xingtu/creator_library.py`), and the
 * formatting helpers mirror the library page's rules: platform raw value first, `≈` for values the
 * platform itself marked approximate, `暂无数据` for missing values — never a guessed number.
 */
import type { CreatorLibraryDetail, LibraryMetric } from "./types";

export function fieldByKey(payload: Record<string, unknown>, fieldKey: string): Record<string, unknown> | null {
  const modules = payload.modules;
  if (!modules || typeof modules !== "object" || Array.isArray(modules)) return null;
  for (const module of Object.values(modules as Record<string, unknown>)) {
    const fields = (module as Record<string, unknown> | null)?.fields;
    if (!Array.isArray(fields)) continue;
    for (const field of fields) {
      if (field && typeof field === "object" && (field as Record<string, unknown>).field_key === fieldKey) {
        return field as Record<string, unknown>;
      }
    }
  }
  return null;
}

function collected(field: Record<string, unknown> | null): Record<string, unknown> | null {
  return field && field.status === "COLLECTED" ? field : null;
}

function numericValue(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const text = typeof value === "string" ? value.replace(/,/g, "") : value;
  const amount = Number(text);
  return Number.isFinite(amount) ? amount : null;
}

/** A plain (non-structured) field such as `basic.followers` or `basic.nickname`. */
function textField(payload: Record<string, unknown>, fieldKey: string): string | null {
  const field = collected(fieldByKey(payload, fieldKey));
  return field && typeof field.value === "string" ? field.value : null;
}

function listField(payload: Record<string, unknown>, fieldKey: string): string[] {
  const field = collected(fieldByKey(payload, fieldKey));
  const value = field?.value;
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : [];
}

/** `{kind: "number", amount, bound}` fields (followers, monthly deep users, follower growth). */
function numberMetric(payload: Record<string, unknown>, fieldKey: string): LibraryMetric {
  const field = collected(fieldByKey(payload, fieldKey));
  if (!field) return emptyMetric();
  const value = field.value && typeof field.value === "object" ? (field.value as Record<string, unknown>) : {};
  const amount = numericValue(value.amount);
  const raw = typeof field.raw_value === "string" && field.raw_value !== "" ? field.raw_value : null;
  return {
    value: amount,
    raw_value: raw ?? (amount === null ? null : String(amount)),
    unit: typeof field.unit === "string" ? field.unit : null,
    is_approximate: Boolean(field.is_approximate) || value.bound === "approximate",
    status: String(field.status ?? "NOT_AVAILABLE"),
    observed_at: typeof field.observed_at === "string" ? field.observed_at : null,
  };
}

/**
 * `{kind: "structured", data: {...}}` members such as `expected_cpm.data.cpm_21_60`.
 *
 * The library read model stores only the numeric member for these fields (no `raw_value`), so the
 * page renders the number itself — matching `_metric(..., raw_column=None)` in `product_queries.py`.
 * Reusing the field's whole `raw_value` here would print the raw JSON blob instead of the value.
 */
function memberMetric(payload: Record<string, unknown>, fieldKey: string, memberPath: string[]): LibraryMetric {
  const field = collected(fieldByKey(payload, fieldKey));
  if (!field) return emptyMetric();
  const value = field.value && typeof field.value === "object" ? (field.value as Record<string, unknown>) : {};
  let cursor: unknown = value.data;
  for (const member of memberPath) {
    cursor = cursor && typeof cursor === "object" ? (cursor as Record<string, unknown>)[member] : undefined;
  }
  const amount = numericValue(cursor);
  return {
    value: amount,
    raw_value: null,
    unit: typeof field.unit === "string" ? field.unit : null,
    is_approximate: amount !== null && Boolean(field.is_approximate),
    status: String(field.status ?? "NOT_AVAILABLE"),
    observed_at: typeof field.observed_at === "string" ? field.observed_at : null,
  };
}

function emptyMetric(): LibraryMetric {
  return { value: null, raw_value: null, unit: null, is_approximate: false, status: "NO_DATA", observed_at: null };
}

/**
 * The library keeps a `field_sources` allowlist per field. The snapshot carries the same allowlisted
 * attributes on each module field, so the task entry can show the same provenance detail shape.
 */
function fieldSources(payload: Record<string, unknown>): Record<string, unknown> {
  const sources: Record<string, unknown> = {};
  const modules = payload.modules;
  if (!modules || typeof modules !== "object" || Array.isArray(modules)) return sources;
  for (const module of Object.values(modules as Record<string, unknown>)) {
    const fields = (module as Record<string, unknown> | null)?.fields;
    if (!Array.isArray(fields)) continue;
    for (const field of fields) {
      if (!field || typeof field !== "object") continue;
      const record = field as Record<string, unknown>;
      const key = record.field_key;
      if (typeof key !== "string" || key in sources) continue;
      sources[key] = {
        observed_at: record.observed_at ?? null,
        status: record.status ?? null,
        source_kind: record.source_kind ?? null,
        source_contract: record.source_contract ?? null,
        path_ref: record.path_ref ?? null,
        unit: record.unit ?? null,
        period_label: record.period_label ?? null,
      };
    }
  }
  return sources;
}

function moduleStatuses(payload: Record<string, unknown>): Record<string, string | null> {
  const statuses: Record<string, string | null> = {};
  const modules = payload.modules;
  if (!modules || typeof modules !== "object" || Array.isArray(modules)) return statuses;
  for (const [key, module] of Object.entries(modules as Record<string, unknown>)) {
    const status = (module as Record<string, unknown> | null)?.status;
    statuses[key] = typeof status === "string" ? status : null;
  }
  return statuses;
}

function allFields(payload: Record<string, unknown>): Array<Record<string, unknown>> {
  const fields: Array<Record<string, unknown>> = [];
  const modules = payload.modules;
  if (!modules || typeof modules !== "object" || Array.isArray(modules)) return fields;
  for (const module of Object.values(modules as Record<string, unknown>)) {
    const entries = (module as Record<string, unknown> | null)?.fields;
    if (Array.isArray(entries)) fields.push(...(entries as Array<Record<string, unknown>>));
  }
  return fields;
}

/**
 * Build the library-shaped view of a task snapshot.
 *
 * `data_updated_at` uses the snapshot's own capture time, and `latest_snapshot_id` the snapshot the
 * task holds — never the library's cross-task "latest projection" for the same creator. A task
 * detail page must not show a newer crawl than the one the task actually produced.
 */
export function snapshotCreatorView(
  payload: Record<string, unknown>,
  identity: {
    creator_id: string;
    platform_creator_id: string;
    snapshot_id: string | null;
    observed_at: string | null;
  },
): CreatorLibraryDetail {
  const fields = allFields(payload);
  const collectedCount = fields.filter((field) => field.status === "COLLECTED").length;
  const failedCount = fields.filter((field) => field.status === "FAILED").length;

  return {
    creator_id: identity.creator_id,
    platform: "douyin_xingtu",
    platform_creator_id: identity.platform_creator_id,
    display_name: textField(payload, "nickname"),
    avatar_uri: textField(payload, "avatar_uri"),
    creator_type_label: textField(payload, "creator_type_label"),
    province: textField(payload, "province"),
    city: textField(payload, "city"),
    industry_labels: listField(payload, "industry_labels"),
    mcn_name: textField(payload, "mcn_name"),
    introduction: textField(payload, "introduction"),
    gender: textField(payload, "gender"),
    content_theme_labels: listField(payload, "content_theme_labels"),
    followers: numberMetric(payload, "followers"),
    monthly_deep_users: numberMetric(payload, "monthly_deep_users"),
    monthly_connected_users: numberMetric(payload, "monthly_connected_users"),
    monthly_follower_growth_rate: numberMetric(payload, "monthly_follower_growth_rate"),
    interaction_rate: memberMetric(payload, "interaction_rate", ["value"]),
    completion_rate: memberMetric(payload, "completion_rate", ["value"]),
    expected_cpm_21_60: memberMetric(payload, "expected_cpm", ["cpm_21_60"]),
    expected_cpm_60_plus: memberMetric(payload, "expected_cpm", ["cpm_60"]),
    expected_cpe_21_60: memberMetric(payload, "expected_cpe", ["cpe_21_60"]),
    expected_cpe_60_plus: memberMetric(payload, "expected_cpe", ["cpe_60"]),
    profile_complete: Boolean(payload.profile_complete),
    pipeline_complete: Boolean(payload.pipeline_complete),
    data_updated_at: identity.observed_at,
    latest_snapshot_id: identity.snapshot_id,
    collected_field_count: collectedCount,
    failed_field_count: failedCount,
    field_sources: fieldSources(payload),
    module_statuses: moduleStatuses(payload),
    profile_payload: payload,
  };
}
