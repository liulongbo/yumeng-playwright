import { useMemo, useState } from "react";
import type {
  CapabilityDimension,
  CapabilityField,
  CapabilityOption,
  LiveFilterSelection,
  LiveRequirementForm,
  RegionNode,
} from "./types";

export const EMPTY_LIVE_FILTERS: LiveFilterSelection[] = [];

function unitLabel(unit: string | null | undefined) {
  if (unit === "ten_thousand_count") return "万";
  if (unit === "yuan") return "元";
  if (unit === "count") return "";
  return unit ?? "";
}

function optionLabel(field: CapabilityField, value: string) {
  return field.options.find((option) => option.value === value)?.label ?? value;
}

function dimensionLabel(field: CapabilityField, key: string) {
  return field.dimensions.find((dimension) => dimension.key === key)?.label ?? key;
}

function regionLabel(field: CapabilityField, provinceCode: string, city?: string | null) {
  const province = field.region_tree.find((node) => node.value === provinceCode)?.label ?? provinceCode;
  return city ? `${province} / ${city}` : province;
}

function updateFilter(
  filters: LiveFilterSelection[],
  field: string,
  update: (current: LiveFilterSelection | undefined) => LiveFilterSelection | null,
) {
  const current = filters.find((item) => item.field === field);
  const next = update(current);
  const rest = filters.filter((item) => item.field !== field);
  return next ? [...rest, next] : rest;
}

function LiveOptionField({
  field,
  selection,
  onChange,
}: {
  field: CapabilityField;
  selection?: LiveFilterSelection;
  onChange: (next: LiveFilterSelection | null) => void;
}) {
  const values = selection?.values ?? [];
  const multi = field.control === "multi-select";
  function toggle(value: string) {
    if (!multi) {
      onChange(values[0] === value ? null : { field: field.field, values: [value] });
      return;
    }
    const next = values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
    onChange(next.length ? { field: field.field, values: next } : null);
  }
  return (
    <div className="field full">
      <span>{field.label} <i>已核验</i></span>
      <div className="option-grid">
        {field.options.map((option) => (
          <label key={option.value}>
            <input
              type={multi ? "checkbox" : "radio"}
              name={field.field}
              checked={values.includes(option.value)}
              onChange={() => toggle(option.value)}
              disabled={Boolean(field.disabled_reason)}
            />
            {option.label}
          </label>
        ))}
      </div>
      {field.disabled_reason && <small>当前账号不可用：{field.disabled_reason}</small>}
      {values.length > 0 && (
        <button type="button" className="button ghost small" onClick={() => onChange(null)}>
          清除该项
        </button>
      )}
    </div>
  );
}

function selectedPreset(field: CapabilityField, selection?: LiveFilterSelection) {
  const range = selection?.range;
  if (!range) return undefined;
  return field.options.find(
    (option) =>
      option.range &&
      (option.range.min === null ? range.min === null : Number(option.range.min) === range.min) &&
      (option.range.max === null ? range.max === null : Number(option.range.max) === range.max),
  );
}

function LiveRangeField({
  field,
  selection,
  onChange,
}: {
  field: CapabilityField;
  selection?: LiveFilterSelection;
  onChange: (next: LiveFilterSelection | null) => void;
}) {
  const unit: "count" | "ten_thousand_count" | "yuan" =
    field.unit === "ten_thousand_count" || field.unit === "yuan" ? field.unit : "count";
  const preset = selectedPreset(field, selection);
  const [custom, setCustom] = useState(Boolean(selection?.range && !preset));
  const range = selection?.range ?? null;
  function setRange(min: number | null, max: number | null) {
    if (min === null && max === null) {
      onChange(null);
      return;
    }
    onChange({ field: field.field, values: [], range: { min, max, unit } });
  }
  function selectPreset(value: string) {
    if (value === "custom") {
      setCustom(true);
      if (!range) setRange(field.range_constraints?.min ?? 0, null);
      return;
    }
    setCustom(false);
    const option = field.options.find((item) => item.value === value);
    if (!option?.range) {
      onChange(null);
      return;
    }
    setRange(
      option.range.min === null ? null : Number(option.range.min),
      option.range.max === null ? null : Number(option.range.max),
    );
  }
  return (
    <div className="field">
      <span>{field.label} <i>已核验</i></span>
      <select
        aria-label={field.label}
        value={preset?.value ?? (selection?.range ? "custom" : "")}
        onChange={(event) => selectPreset(event.target.value)}
        disabled={Boolean(field.disabled_reason)}
      >
        <option value="">全部／不限</option>
        {field.options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
        <option value="custom">自定义</option>
      </select>
      {custom && (
        <div className="range-fields">
          <input
            aria-label={`${field.label}下限`}
            type="number"
            min={field.range_constraints?.min ?? 0}
            max={field.range_constraints?.max}
            value={range?.min ?? ""}
            onChange={(event) => setRange(event.target.value === "" ? null : Number(event.target.value), range?.max ?? null)}
          />
          <b>—</b>
          <input
            aria-label={`${field.label}上限`}
            type="number"
            min={field.range_constraints?.min ?? 0}
            max={field.range_constraints?.max}
            value={range?.max ?? ""}
            onChange={(event) => setRange(range?.min ?? null, event.target.value === "" ? null : Number(event.target.value))}
          />
          <em>{unitLabel(unit)}</em>
        </div>
      )}
      <small>
        {field.range_constraints
          ? `平台范围 ${field.range_constraints.min}—${field.range_constraints.max}${unitLabel(unit)}；留空表示该边界不限。`
          : "留空表示该边界不限。"}
      </small>
      {field.disabled_reason && <small>当前账号不可用：{field.disabled_reason}</small>}
    </div>
  );
}

function LiveProfileField({
  field,
  selection,
  onChange,
}: {
  field: CapabilityField;
  selection?: LiveFilterSelection;
  onChange: (next: LiveFilterSelection | null) => void;
}) {
  const profile = selection?.profile ?? [];
  function toggle(dimension: CapabilityDimension, value: string) {
    const current = profile.find((item) => item.key === dimension.key)?.values ?? [];
    const nextValues = dimension.control === "single-select"
      ? current.includes(value) ? [] : [value]
      : current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
    const nextProfile = profile.filter((item) => item.key !== dimension.key);
    if (nextValues.length) nextProfile.push({ key: dimension.key, values: nextValues });
    onChange(nextProfile.length ? { field: field.field, values: [], profile: nextProfile } : null);
  }
  return (
    <div className="field full profile-field">
      <span>{field.label} <i>已核验</i></span>
      {field.dimensions.map((dimension) => {
        const values = profile.find((item) => item.key === dimension.key)?.values ?? [];
        return (
          <div className="profile-dimension" key={dimension.key}>
            <strong>{dimension.label}</strong>
            {dimension.control === "single-select" ? (
              <select
                aria-label={dimension.label}
                value={values[0] ?? ""}
                onChange={(event) => {
                  if (!event.target.value) {
                    const next = profile.filter((item) => item.key !== dimension.key);
                    onChange(next.length ? { field: field.field, values: [], profile: next } : null);
                    return;
                  }
                  const next = profile.filter((item) => item.key !== dimension.key);
                  next.push({ key: dimension.key, values: [event.target.value] });
                  onChange({ field: field.field, values: [], profile: next });
                }}
              >
                <option value="">不限</option>
                {dimension.options.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            ) : (
              <div className="option-grid">
                {dimension.options.map((option) => (
                  <label key={option.value}>
                    <input
                      type="checkbox"
                      checked={values.includes(option.value)}
                      onChange={() => toggle(dimension, option.value)}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        );
      })}
      {field.disabled_reason && <small>当前账号不可用：{field.disabled_reason}</small>}
      {profile.length > 0 && (
        <button type="button" className="button ghost small" onClick={() => onChange(null)}>
          清除该项
        </button>
      )}
    </div>
  );
}

function LiveRegionField({
  field,
  selection,
  onChange,
}: {
  field: CapabilityField;
  selection?: LiveFilterSelection;
  onChange: (next: LiveFilterSelection | null) => void;
}) {
  const regions = selection?.regions ?? [];
  const [province, setProvince] = useState("");
  const [city, setCity] = useState("");
  const node: RegionNode | undefined = field.region_tree.find((item) => item.value === province);
  function commit(provinceCode: string, cityValue: string) {
    if (!provinceCode) return;
    let next = regions.filter((item) => item.province_code !== provinceCode || (cityValue ? item.city : false));
    if (cityValue) next = next.filter((item) => !(item.province_code === provinceCode && !item.city));
    if (!next.some((item) => item.province_code === provinceCode && (item.city ?? null) === (cityValue || null))) {
      next = [...next, { province_code: provinceCode, ...(cityValue ? { city: cityValue } : {}) }];
    }
    onChange({ field: field.field, values: [], regions: next });
  }
  return (
    <div className="field full">
      <span>{field.label} <i>已核验</i></span>
      <div className="region-picker">
        <select
          aria-label="直播省级地域"
          value={province}
          onChange={(event) => {
            const next = event.target.value;
            setProvince(next);
            setCity("");
            if (next) commit(next, "");
          }}
        >
          <option value="">选择省份</option>
          {field.region_tree.map((item) => (
            <option key={item.value} value={item.value}>{item.label}</option>
          ))}
        </select>
        <select
          aria-label="直播二级地域"
          value={city}
          onChange={(event) => {
            const next = event.target.value;
            setCity(next);
            if (province) commit(province, next);
          }}
          disabled={!node?.children.length}
        >
          <option value="">整省</option>
          {node?.children.map((item) => (
            <option key={item.value} value={item.value}>{item.label}</option>
          ))}
        </select>
      </div>
      <div className="selection-chips">
        {regions.map((item) => (
          <button
            type="button"
            key={`${item.province_code}:${item.city ?? ""}`}
            onClick={() => {
              const next = regions.filter((current) => current !== item);
              onChange(next.length ? { field: field.field, values: [], regions: next } : null);
            }}
          >
            {regionLabel(field, item.province_code, item.city)} ×
          </button>
        ))}
      </div>
      {field.disabled_reason && <small>当前账号不可用：{field.disabled_reason}</small>}
    </div>
  );
}

export function LiveFilterFields({
  fields,
  values,
  onChange,
}: {
  fields: CapabilityField[];
  values: LiveFilterSelection[];
  onChange: (next: LiveFilterSelection[]) => void;
}) {
  const groups = useMemo(() => {
    const order: string[] = [];
    const grouped = new Map<string, CapabilityField[]>();
    for (const field of fields) {
      const group = field.group ?? "其他筛选";
      if (!grouped.has(group)) {
        grouped.set(group, []);
        order.push(group);
      }
      grouped.get(group)!.push(field);
    }
    return order.map((group) => ({ group, fields: grouped.get(group)! }));
  }, [fields]);
  const hasIncompatible = fields.some((field) => field.incompatible_with.length > 0);
  return (
    <>
      {hasIncompatible && (
        <div className="profile-exclusion">部分画像条件互斥，选择一侧会清空另一侧。</div>
      )}
      {groups.map(({ group, fields: groupFields }) => (
        <fieldset className="capability-group" key={group}>
          <legend>{group}</legend>
          <p>平台真实筛选项；未选择表示不限。</p>
          <div className="field-grid">
            {groupFields.map((field) => {
              const selection = values.find((item) => item.field === field.field);
              return (
                <LiveFilterField
                  key={field.field}
                  field={field}
                  selection={selection}
                  onChange={(next) => {
                    const updated = updateFilter(values, field.field, () => next);
                    if (!next || field.incompatible_with.length === 0) {
                      onChange(updated);
                      return;
                    }
                    const incompatible = new Set(field.incompatible_with);
                    onChange(
                      updated.filter(
                        (item) => item.field === field.field || !incompatible.has(item.field),
                      ),
                    );
                  }}
                />
              );
            })}
          </div>
        </fieldset>
      ))}
    </>
  );
}

function LiveFilterField({
  field,
  selection,
  onChange,
}: {
  field: CapabilityField;
  selection?: LiveFilterSelection;
  onChange: (next: LiveFilterSelection | null) => void;
}) {
  if (field.field === "live_region") {
    return <LiveRegionField field={field} selection={selection} onChange={onChange} />;
  }
  if (field.control === "profile-group") {
    return <LiveProfileField field={field} selection={selection} onChange={onChange} />;
  }
  if (field.control === "range") {
    return <LiveRangeField field={field} selection={selection} onChange={onChange} />;
  }
  return <LiveOptionField field={field} selection={selection} onChange={onChange} />;
}

export function validateLiveFilters(
  form: LiveRequirementForm,
  fields: CapabilityField[],
  policy?: { fields: string[]; incompatible: string[][] } | null,
) {
  if ((form.keyword ?? "").trim().length === 0 && form.live_filters.length === 0) {
    return "请填写达人昵称/平台 ID，或至少选择一项直播筛选条件。";
  }
  if (form.target_count < 1 || form.target_count > 70) {
    return "直播单任务目标数量必须在 1—70 之间。";
  }
  const selectedFields = form.live_filters.map((item) => item.field);
  if (policy) {
    const selected = new Set(selectedFields);
    for (const pair of policy.incompatible) {
      if (pair.every((field) => selected.has(field))) {
        const labels = pair.map((field) => fields.find((item) => item.field === field)?.label ?? field);
        return `所选条件不能同时使用：${labels.join("、")}。`;
      }
    }
  }
  for (const selection of form.live_filters) {
    const field = fields.find((item) => item.field === selection.field);
    if (!field) return `当前平台不支持筛选条件：${selection.field}`;
    if (field.disabled_reason) return `${field.label}当前不可用：${field.disabled_reason}`;
    if (field.control === "range" && selection.range) {
      if (selection.range.min !== null && selection.range.max !== null && selection.range.min > selection.range.max) {
        return `${field.label}的下限不能大于上限。`;
      }
    }
    if (field.control === "profile-group" && !selection.profile?.length) {
      return `${field.label}尚未选择具体选项。`;
    }
    if (selection.field === "live_region" && !selection.regions?.length) {
      return `${field.label}尚未选择地域。`;
    }
  }
  const fieldsWithOptions = form.live_filters.filter((item) => {
    const field = fields.find((entry) => entry.field === item.field);
    return field?.control === "single-select" || field?.control === "multi-select";
  });
  for (const item of fieldsWithOptions) {
    if (!item.values.length) {
      const field = fields.find((entry) => entry.field === item.field);
      return `${field?.label ?? item.field}尚未选择选项。`;
    }
  }
  return "";
}

export function liveFilterSummary(form: LiveRequirementForm, fields: CapabilityField[]) {
  const result: string[] = [];
  if ((form.keyword ?? "").trim()) result.push(`关键词/ID：${form.keyword!.trim()}`);
  for (const selection of form.live_filters) {
    const field = fields.find((item) => item.field === selection.field);
    if (!field) {
      result.push(selection.field);
      continue;
    }
    if (selection.values?.length) {
      result.push(`${field.label}：${selection.values.map((value) => optionLabel(field, value)).join("、")}`);
    } else if (selection.range) {
      const unit = unitLabel(selection.range.unit);
      const min = selection.range.min ?? "不限";
      const max = selection.range.max ?? "不限";
      result.push(`${field.label}：${min}—${max}${unit}`);
    } else if (selection.regions?.length) {
      result.push(`${field.label}：${selection.regions.map((item) => regionLabel(field, item.province_code, item.city)).join("、")}`);
    } else if (selection.profile?.length) {
      const parts = selection.profile.map((dimension) => {
        const definition = field.dimensions.find((item) => item.key === dimension.key);
        const labels = dimension.values.map(
          (value) => definition?.options.find((option) => option.value === value)?.label ?? value,
        );
        return `${definition?.label ?? dimension.key}-${labels.join("/")}`;
      });
      result.push(`${field.label}：${parts.join("；")}`);
    }
  }
  return result;
}
