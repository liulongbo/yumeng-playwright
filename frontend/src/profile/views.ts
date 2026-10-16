/**
 * One place that turns a `FieldObservation` envelope plus its catalog entry into display state.
 *
 * Nothing here invents a unit or a scale: a percentage is produced only for a field the verified
 * contract registers as `kind: "ratio"`, a count keeps the platform's own number, and a field that
 * did not reach `COLLECTED` becomes an explicit state instead of a zero or an empty string.
 */
import { fieldStatusText } from "../format";
import {
  catalogEntry,
  fieldLabel,
  readField,
  readValue,
  type CatalogIndex,
} from "../fieldCatalog";
import { isBlank, numberOrNull, ratioPercentText, shortText } from "../format";

export interface FieldView {
  moduleKey: string;
  fieldKey: string;
  label: string;
  kind: string;
  unit: string | null;
  periodLabel: string | null;
  /** The envelope exists in the payload. */
  present: boolean;
  collected: boolean;
  status: string;
  statusText: string;
  /** The extracted platform value (`data`, `amount`, or the scalar itself). */
  data: unknown;
  blank: boolean;
  approximate: boolean;
  observedAt: string | null;
  /** Formatted display text for a scalar/one-line value. */
  text: string;
  /** An evidence-backed clarification for the shown text (for example the platform gender code). */
  note?: string;
  /** Why the value is not shown, when it is not `COLLECTED`. */
  state: string | null;
}

function structuredText(value: unknown): string {
  if (Array.isArray(value)) return value.length ? `${value.length} 条记录` : "—";
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if ("value" in record) return structuredText(record.value);
    if ("label" in record && Object.keys(record).length === 1 && typeof record.label === "string") {
      return shortText(record.label, 40);
    }
    if ("amount" in record) return structuredText(record.amount);
    const size = Object.keys(record).length;
    return size ? `平台结构化数据（${size} 项）` : "—";
  }
  return "—";
}

/**
 * Value labels confirmed against the live platform page.
 *
 * `basic.gender` stores the platform's numeric code; the 巨量星图 creator homepage was read on
 * 2026-10-14 and displayed 女 for the stored code `2`, so that one mapping is registered here.
 * `1` (男) and `0` (未知/未标注) are the platform's conventional codes and appear in the stored data
 * (measured 2026-10-15: 12 × `1`, 10 × `2`, 1 × `0`), but were **not** re-confirmed against the live
 * page in this project, so the note says so instead of implying a verified mapping.
 */
export const VALUE_LABEL_OVERRIDES: Record<
  string,
  (raw: string) => { text: string; note?: string }
> = {
  "basic.gender": (raw) => {
    if (raw === "2") return { text: "女", note: "平台编码 2（2026-10-14 线上确证）" };
    if (raw === "1") return { text: "男", note: "平台编码 1（常规编码，未经本项目线上复核）" };
    if (raw === "0") return { text: "未知", note: "平台编码 0（常规编码，未经本项目线上复核）" };
    return { text: `平台编码 ${raw}`, note: "编码含义未登记" };
  },
};

/** The rail's 性别 datum: the mapped label plus the code it came from. */
export function genderDisplay(
  payload: Record<string, unknown>,
): { text: string; note: string } | null {
  const field = readField(payload, "gender");
  if (!field || field.status !== "COLLECTED") return null;
  const value = readValue(field);
  if (typeof value !== "string" || !value.trim()) return null;
  const code = value.trim();
  const labelled = VALUE_LABEL_OVERRIDES["basic.gender"](code);
  return { text: labelled.text, note: labelled.note ?? `平台编码 ${code}` };
}

/**
 * Why a collected field shows no value.
 *
 * An empty list (or the platform's `"[]"` / `"{}"` text form) is a well-defined platform answer:
 * "nothing here".  An empty object that the platform did not register as an empty marker means we
 * could not extract a usable member, which is a different state and is reported as such.
 */
function blankState(data: unknown): string {
  if (Array.isArray(data)) return "平台暂无数据";
  if (typeof data === "string" && ["[]", "{}"].includes(data.trim())) return "平台暂无数据";
  return "平台返回空值";
}

export function fieldView(
  payload: Record<string, unknown>,
  index: CatalogIndex,
  moduleKey: string,
  fieldKey: string,
): FieldView {
  const entry = catalogEntry(index, fieldKey, moduleKey);
  const field = readField(payload, fieldKey);
  const status = String(field?.status ?? entry?.missing_source_status ?? "MISSING_SOURCE");
  const collected = status === "COLLECTED";
  const data = collected ? readValue(field) : null;
  const blank = isBlank(data);
  const kind = entry?.kind ?? "structured";
  const approximate = Boolean(field?.is_approximate);
  let text = "—";
  let note: string | undefined;
  const override = VALUE_LABEL_OVERRIDES[`${moduleKey}.${fieldKey}`];
  if (collected && !blank) {
    if (override && typeof data === "string") {
      const labelled = override(data);
      text = labelled.text;
      note = labelled.note;
    } else if (kind === "ratio") text = ratioPercentText(data);
    else if (kind === "number") text = countOrDash(data, approximate);
    else if (typeof data === "number") text = data.toLocaleString("zh-CN");
    else if (typeof data === "string") {
      // A registered `text` field is an identifier or a label (`星图ID`, `抖音号`, `性别`), never a
      // count: it is shown exactly as the platform sent it.  Only a structured metric string that is
      // short enough to survive IEEE-754 (<= 12 digits, e.g. `1346919`, `929620`) is grouped, so a
      // 19-digit星图 ID is never parsed as a float and silently rounded.
      const isIdentifierLike = kind === "text";
      const isSafeIntegerString = /^\d{1,12}$/.test(data.trim());
      text =
        !isIdentifierLike && isSafeIntegerString
          ? countOrDash(data, approximate)
          : shortText(data, 64);
    } else text = structuredText(data);
  }
  return {
    moduleKey,
    fieldKey,
    label: fieldLabel(index, fieldKey, moduleKey),
    kind,
    unit: entry?.unit ?? null,
    periodLabel: entry?.period_label ?? null,
    present: Boolean(field),
    collected,
    status,
    statusText: fieldStatusText(status),
    data,
    blank,
    approximate,
    observedAt: typeof field?.observed_at === "string" ? field.observed_at : null,
    text,
    note,
    state: collected && blank ? blankState(data) : collected ? null : fieldStatusText(status),
  };
}

export function countOrDash(value: unknown, approximate = false): string {
  const amount = numberOrNull(value);
  if (amount === null) return "—";
  const text = amount.toLocaleString("zh-CN");
  return approximate ? `≈${text}` : text;
}

/** Period suffix for a label, for example `月`. */
export function periodSuffix(view: FieldView): string | undefined {
  return view.periodLabel ?? undefined;
}
