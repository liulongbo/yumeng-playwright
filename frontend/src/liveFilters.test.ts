import { describe, expect, it } from "vitest";
import type { CapabilityField, LiveRequirementForm } from "./types";
import { liveFilterSummary, validateLiveFilters } from "./liveFilters";

function form(overrides: Partial<LiveRequirementForm> = {}): LiveRequirementForm {
  return {
    schema_version: "requirement_form.v2",
    platform: "douyin_xingtu",
    creator_scene: "live_square",
    keyword: null,
    live_filters: [],
    target_count: 5,
    ...overrides,
  };
}

const content: CapabilityField = {
  field: "live_content_type",
  label: "内容类型",
  operators: ["in"],
  control: "single-select",
  options: [{ value: "fashion", label: "时尚" }],
  dimensions: [],
  region_tree: [],
  incompatible_with: [],
  currencies: [],
  cooperation_forms: [],
};

const followers: CapabilityField = {
  field: "live_followers",
  label: "粉丝量级",
  operators: ["range"],
  control: "range",
  unit: "ten_thousand_count",
  options: [
    { value: "100_300", label: "100w-300w", range: { min: 100, max: 300 } },
  ],
  dimensions: [],
  region_tree: [],
  incompatible_with: [],
  currencies: [],
  cooperation_forms: [],
};

const profile: CapabilityField = {
  field: "live_fan_profile",
  label: "粉丝画像",
  operators: ["compound"],
  control: "profile-group",
  options: [],
  dimensions: [
    {
      key: "age",
      label: "粉丝年龄",
      control: "multi-select",
      options: [{ value: "18-23", label: "18-23岁居多" }],
    },
  ],
  region_tree: [],
  incompatible_with: [],
  currencies: [],
  cooperation_forms: [],
};

const fanProfile: CapabilityField = {
  ...profile,
  incompatible_with: ["live_viewer_profile"],
};

const viewerProfile: CapabilityField = {
  ...profile,
  field: "live_viewer_profile",
  label: "直播间观众画像",
  incompatible_with: ["live_fan_profile"],
};

const fields = [content, followers, profile];

describe("live filter form", () => {
  it("allows a filter-only live requirement and rejects an empty one", () => {
    expect(validateLiveFilters(form({ live_filters: [{ field: "live_content_type", values: ["fashion"] }] }), fields)).toBe("");
    expect(validateLiveFilters(form(), fields)).toContain("至少选择一项");
  });

  it("rejects Xingtu fan and viewer profiles together", () => {
    const policy = {
      fields: ["live_fan_profile", "live_viewer_profile"],
      incompatible: [["live_viewer_profile", "live_fan_profile"]],
    };
    const both = form({
      live_filters: [
        { field: "live_fan_profile", values: [], profile: [{ key: "age", values: ["18-23"] }] },
        { field: "live_viewer_profile", values: [], profile: [{ key: "age", values: ["18-23"] }] },
      ],
    });
    expect(validateLiveFilters(both, [fanProfile, viewerProfile], policy)).toContain("不能同时使用");
    expect(
      validateLiveFilters(
        form({
          live_filters: [
            { field: "live_fan_profile", values: [], profile: [{ key: "age", values: ["18-23"] }] },
          ],
        }),
        [fanProfile, viewerProfile],
        policy,
      ),
    ).toBe("");
  });

  it("rejects disabled fields and incompatible combinations", () => {
    const disabled = { ...content, disabled_reason: "当前账号不可用" };
    expect(
      validateLiveFilters(
        form({ live_filters: [{ field: "live_content_type", values: ["fashion"] }] }),
        [disabled],
      ),
    ).toContain("当前不可用");
    expect(
      validateLiveFilters(
        form({
          live_filters: [
            { field: "live_content_type", values: ["fashion"] },
            { field: "live_fan_profile", values: [], profile: [{ key: "age", values: ["18-23"] }] },
          ],
        }),
        fields,
        { fields: ["live_content_type", "live_fan_profile"], incompatible: [["live_content_type", "live_fan_profile"]] },
      ),
    ).toContain("不能同时使用");
  });

  it("summarizes options, ranges and profiles with platform labels", () => {
    const summary = liveFilterSummary(
      form({
        live_filters: [
          { field: "live_content_type", values: ["fashion"] },
          { field: "live_followers", values: [], range: { min: 100, max: 300, unit: "ten_thousand_count" } },
          { field: "live_fan_profile", values: [], profile: [{ key: "age", values: ["18-23"] }] },
        ],
      }),
      fields,
    );
    expect(summary).toEqual([
      "内容类型：时尚",
      "粉丝量级：100—300万",
      "粉丝画像：粉丝年龄-18-23岁居多",
    ]);
  });

  it("keeps the 70 target limit in client validation", () => {
    expect(
      validateLiveFilters(
        form({ target_count: 71, live_filters: [{ field: "live_content_type", values: ["fashion"] }] }),
        fields,
      ),
    ).toContain("1—70");
  });
});
