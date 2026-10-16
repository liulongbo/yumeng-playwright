import { describe, expect, it } from "vitest";
import { indexCatalog } from "../fieldCatalog";
import type { ProfileFieldCatalog } from "../types";
import { fieldView } from "./views";

const CATALOG: ProfileFieldCatalog = {
  platform: "douyin_xingtu",
  contract_version: "test",
  modules: [
    {
      key: "basic",
      fields: [
        entry("followers", "粉丝数", "number", { unit: "count" }),
        entry("monthly_follower_growth_rate", "月涨粉率", "ratio", { unit: "ratio", period: "月" }),
        entry("province", "省份", "text"),
        entry("platform_creator_id", "星图ID", "text"),
        entry("douyin_unique_id", "抖音号", "text"),
      ],
    },
    {
      key: "spread",
      fields: [
        entry("commercial_play_count", "商业播放量", "structured"),
        entry("commercial_cpm_20_60", "20-60秒商业 CPM", "structured"),
        entry("play_stability", "播放稳定性", "structured"),
      ],
    },
    {
      key: "seeding",
      fields: [entry("a3_increment", "A3 增量及同行排名", "structured")],
    },
  ],
};

function entry(
  key: string,
  name: string,
  kind: string,
  options: { unit?: string; period?: string } = {},
) {
  return {
    key,
    name,
    contract_name: name,
    name_source: "contract" as const,
    kind,
    unit: options.unit ?? null,
    period_label: options.period ?? null,
    empty_values: [],
    missing_source_status: null,
  };
}

const INDEX = indexCatalog(CATALOG);

function payload(fields: Array<Record<string, unknown>>) {
  const basicKeys = ["followers", "monthly_follower_growth_rate", "province", "platform_creator_id", "douyin_unique_id"];
  return {
    modules: {
      basic: { status: "COLLECTED", fields: fields.filter((f) => basicKeys.includes(String(f.field_key))) },
      spread: { status: "COLLECTED", fields: fields.filter((f) => ["commercial_play_count", "commercial_cpm_20_60", "play_stability"].includes(String(f.field_key))) },
      seeding: { status: "COLLECTED", fields: fields.filter((f) => String(f.field_key) === "a3_increment") },
    },
  } as Record<string, unknown>;
}

function observation(fieldKey: string, value: unknown, extra: Record<string, unknown> = {}) {
  return { field_key: fieldKey, value, status: "COLLECTED", ...extra };
}

describe("fieldView", () => {
  it("groups an integer platform string but keeps a platform decimal untouched", () => {
    const data = payload([
      observation("commercial_play_count", { kind: "structured", data: "1346919" }),
      observation("commercial_cpm_20_60", { kind: "structured", data: "29.6974" }),
    ]);
    expect(fieldView(data, INDEX, "spread", "commercial_play_count").text).toBe("1,346,919");
    // The platform returned four decimals; re-rounding would change the observed value.
    expect(fieldView(data, INDEX, "spread", "commercial_cpm_20_60").text).toBe("29.6974");
  });

  it("never parses an identifier as a number", () => {
    // Measured: the 19-digit 星图 ID exceeds IEEE-754 integer precision, so grouping it would
    // silently replace the last three digits with zeros.
    const data = payload([
      observation("platform_creator_id", "7503176021160493065"),
      observation("douyin_unique_id", "28264865291"),
    ]);
    expect(fieldView(data, INDEX, "basic", "platform_creator_id").text).toBe("7503176021160493065");
    expect(fieldView(data, INDEX, "basic", "douyin_unique_id").text).toBe("28264865291");
  });

  it("keeps a structured integer longer than 12 digits unformatted", () => {
    const data = payload([observation("commercial_play_count", { kind: "structured", data: "1234567890123" })]);
    expect(fieldView(data, INDEX, "spread", "commercial_play_count").text).toBe("1234567890123");
  });

  it("scales only a field the contract registers as a ratio", () => {
    const data = payload([
      observation(
        "monthly_follower_growth_rate",
        { kind: "number", bound: "exact", amount: "0.01969004266000137" },
        { unit: "ratio", period_label: "月" },
      ),
      observation("followers", { kind: "number", bound: "exact", amount: "1351784" }, { unit: "count" }),
    ]);
    const growth = fieldView(data, INDEX, "basic", "monthly_follower_growth_rate");
    expect(growth.text).toBe("1.97%");
    expect(growth.periodLabel).toBe("月");
    expect(fieldView(data, INDEX, "basic", "followers").text).toBe("1,351,784");
  });

  it("keeps an approximate platform number marked", () => {
    const data = payload([
      observation(
        "followers",
        { kind: "number", bound: "approximate", amount: "11580000" },
        { is_approximate: true, unit: "count" },
      ),
    ]);
    expect(fieldView(data, INDEX, "basic", "followers").text).toBe("≈11,580,000");
  });

  it("reports a state instead of a value when the field was not collected", () => {
    const data = {
      modules: {
        basic: {
          status: "COLLECTED",
          fields: [{ field_key: "province", value: null, status: "NO_DATA" }],
        },
      },
    } as Record<string, unknown>;
    const view = fieldView(data, INDEX, "basic", "province");
    expect(view.collected).toBe(false);
    expect(view.text).toBe("—");
    expect(view.state).toBe("平台暂无数据");
  });

  it("treats an empty structured object as a blank value, not as a zero", () => {
    const data = payload([observation("play_stability", { kind: "structured", data: {} })]);
    const view = fieldView(data, INDEX, "spread", "play_stability");
    expect(view.collected).toBe(true);
    expect(view.blank).toBe(true);
    expect(view.state).toBe("平台返回空值");
  });

  it("shows a label-only structured response as that label", () => {
    const data = payload([observation("play_stability", { kind: "structured", data: { label: "影视娱乐" } })]);
    expect(fieldView(data, INDEX, "spread", "play_stability").text).toBe("影视娱乐");
  });

  it("keeps a platform range string as text", () => {
    const data = payload([observation("a3_increment", { kind: "structured", data: "20,000 - 100,000" })]);
    expect(fieldView(data, INDEX, "seeding", "a3_increment").text).toBe("20,000 - 100,000");
  });

  it("labels a field from the catalog and falls back to the key for an unknown field", () => {
    const data = payload([observation("province", "内蒙古自治区")]);
    expect(fieldView(data, INDEX, "basic", "province").label).toBe("省份");
    expect(fieldView(data, INDEX, "basic", "mcn_name").label).toBe("mcn_name");
  });

  it("marks a field the payload never observed with a missing-source state", () => {
    const view = fieldView(payload([]), INDEX, "spread", "play_stability");
    expect(view.present).toBe(false);
    expect(view.status).toBe("MISSING_SOURCE");
  });
});
