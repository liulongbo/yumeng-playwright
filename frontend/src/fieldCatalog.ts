/**
 * Field labels, kinds and payload access for the creator detail view.
 *
 * The 81 registered profile fields carry no display name in their snapshot envelope (measured over
 * all 78 stored snapshots: every field has `field_key` and no `name`), so the page reads the labels
 * from the verified registry through `/api/platforms/douyin_xingtu/profile-field-catalog`.  When
 * that request fails the page degrades to the English field key instead of inventing a label.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { fieldByKey } from "./snapshotCreator";
import type { ProfileFieldCatalog, ProfileFieldCatalogEntry } from "./types";

export const MODULE_LABELS: Record<string, string> = {
  basic: "基础资料",
  commercial: "商业合作",
  spread: "传播表现",
  seeding: "种草表现",
  fulfillment: "履约能力",
  conversion: "转化价值",
  fans: "连接用户",
  creation: "创作能力",
};

const DEFAULT_STALE_MS = 30 * 60 * 1000;

export function useFieldCatalog() {
  const query = useQuery({
    queryKey: ["profile-field-catalog"],
    queryFn: () => api.profileFieldCatalog(),
    staleTime: DEFAULT_STALE_MS,
    retry: 1,
  });
  return query.data ?? null;
}

export interface CatalogIndex {
  byField: Map<string, ProfileFieldCatalogEntry>;
  byPath: Map<string, ProfileFieldCatalogEntry>;
}

export function indexCatalog(catalog: ProfileFieldCatalog | null): CatalogIndex {
  const byField = new Map<string, ProfileFieldCatalogEntry>();
  const byPath = new Map<string, ProfileFieldCatalogEntry>();
  for (const module of catalog?.modules ?? []) {
    for (const field of module.fields) {
      byPath.set(`${module.key}.${field.key}`, field);
      if (!byField.has(field.key)) byField.set(field.key, field);
    }
  }
  return { byField, byPath };
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Field metadata from the catalog, resolved by `module.field` first and by bare key second. */
export function catalogEntry(
  index: CatalogIndex,
  fieldKey: string,
  moduleKey?: string,
): ProfileFieldCatalogEntry | null {
  if (moduleKey) {
    const exact = index.byPath.get(`${moduleKey}.${fieldKey}`);
    if (exact) return exact;
  }
  return index.byField.get(fieldKey) ?? null;
}

/**
 * Display label for one field.  The verified registry is authoritative; a field the catalog does
 * not know keeps its `field_key` so the page never shows a guessed Chinese name.
 */
export function fieldLabel(index: CatalogIndex, fieldKey: string, moduleKey?: string): string {
  return catalogEntry(index, fieldKey, moduleKey)?.name ?? fieldKey;
}

/** The unit and period the registry registered for a field, or `null`. */
export function fieldUnitPeriod(
  index: CatalogIndex,
  fieldKey: string,
  moduleKey?: string,
): { unit: string | null; periodLabel: string | null } {
  const entry = catalogEntry(index, fieldKey, moduleKey);
  return { unit: entry?.unit ?? null, periodLabel: entry?.period_label ?? null };
}

/** The `FieldObservation` envelope for a field key inside a snapshot/`profile_payload`. */
export function readField(
  payload: Record<string, unknown>,
  fieldKey: string,
): Record<string, unknown> | null {
  return fieldByKey(payload, fieldKey);
}

/**
 * The platform value inside an observation envelope.
 *
 * - `{kind, amount, bound}` number observations expose `amount`;
 * - `{kind: "structured", data}` observations expose `data`;
 * - text/tag observations expose `value` directly.
 */
export function readValue(field: Record<string, unknown> | null): unknown {
  if (!field) return null;
  const value = field.value;
  const item = record(value);
  if (!item) return value ?? null;
  if ("data" in item) return item.data;
  if ("amount" in item) return item.amount;
  return value ?? null;
}

/** The platform value of a field, or `null` when the field is absent or not successfully collected. */
export function readCollected(
  payload: Record<string, unknown>,
  fieldKey: string,
): unknown {
  const field = readField(payload, fieldKey);
  if (!field || field.status !== "COLLECTED") return null;
  return readValue(field);
}

export function fieldStatus(payload: Record<string, unknown>, fieldKey: string): string {
  const field = readField(payload, fieldKey);
  return String(field?.status ?? "MISSING_SOURCE");
}

/** A module's `status` inside a snapshot payload. */
export function moduleStatus(payload: Record<string, unknown>, moduleKey: string): string {
  const module = record(record(payload.modules)?.[moduleKey]);
  return String(module?.status ?? "MISSING_SOURCE");
}

export function moduleFields(
  payload: Record<string, unknown>,
  moduleKey: string,
): Array<Record<string, unknown>> {
  const module = record(record(payload.modules)?.[moduleKey]);
  const fields = module?.fields;
  return Array.isArray(fields)
    ? fields.filter((field): field is Record<string, unknown> => Boolean(record(field)))
    : [];
}

/** All 81 field envelopes of a payload, in module order. */
export function allFields(payload: Record<string, unknown>): Array<Record<string, unknown>> {
  const modules = record(payload.modules);
  if (!modules) return [];
  return Object.keys(modules).flatMap((key) => moduleFields(payload, key));
}

/** Counts of `COLLECTED` / non-success fields inside one module (or the whole payload). */
export function collectionCounts(
  payload: Record<string, unknown>,
  moduleKey?: string,
): { collected: number; failed: number; missing: number; total: number } {
  const fields = moduleKey ? moduleFields(payload, moduleKey) : allFields(payload);
  const collected = fields.filter((field) => field.status === "COLLECTED").length;
  const failed = fields.filter((field) => field.status === "FAILED").length;
  return { collected, failed, missing: fields.length - collected - failed, total: fields.length };
}

export interface PayloadFieldRow {
  moduleKey: string;
  fieldKey: string;
  label: string;
  entry: ProfileFieldCatalogEntry | null;
  field: Record<string, unknown> | null;
}

/** Every registered field of a module paired with its catalog entry and observed envelope. */
export function moduleRows(
  payload: Record<string, unknown>,
  index: CatalogIndex,
  moduleKey: string,
): PayloadFieldRow[] {
  const registered = index.byPath;
  const observed = new Map<string, Record<string, unknown>>();
  for (const field of moduleFields(payload, moduleKey)) {
    const key = String(field.field_key ?? "");
    if (key) observed.set(key, field);
  }
  const ordered: string[] = [];
  for (const [path, entry] of registered) {
    const [pathModule] = path.split(".");
    if (pathModule === moduleKey && !ordered.includes(entry.key)) ordered.push(entry.key);
  }
  for (const key of observed.keys()) {
    if (!ordered.includes(key)) ordered.push(key);
  }
  return ordered.map((fieldKey) => ({
    moduleKey,
    fieldKey,
    label: fieldLabel(index, fieldKey, moduleKey),
    entry: catalogEntry(index, fieldKey, moduleKey),
    field: observed.get(fieldKey) ?? null,
  }));
}
