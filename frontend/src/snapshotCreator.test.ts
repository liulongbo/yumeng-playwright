import { describe, expect, it } from "vitest";
import { snapshotCreatorView } from "./snapshotCreator";

function envelope(fieldKey: string, value: unknown, extra: Record<string, unknown> = {}) {
  return {
    field_key: fieldKey,
    value,
    status: "COLLECTED",
    observed_at: "2026-10-27T20:00:00+08:00",
    ...extra,
  };
}

function numberField(fieldKey: string, amount: string, extra: Record<string, unknown> = {}) {
  return envelope(fieldKey, { kind: "number", amount, bound: "exact" }, extra);
}

const IDENTITY = {
  creator_id: "creator-1",
  platform_creator_id: "578000000001",
  snapshot_id: "snapshot-1",
  observed_at: "2026-10-27T20:00:00+08:00",
};

describe("snapshotCreatorView", () => {
  it("keeps the existing Xingtu mapping unchanged", () => {
    const payload = {
      modules: {
        basic: {
          status: "COLLECTED",
          fields: [
            envelope("nickname", "星图达人"),
            envelope("creator_type_label", "生活"),
            envelope("content_theme_labels", ["种草"]),
            envelope("industry_labels", ["食品饮料"]),
            envelope("gender", "2"),
            numberField("followers", "1351784", { unit: "count" }),
            numberField("monthly_deep_users", "11580000", { unit: "count", is_approximate: true }),
            numberField("monthly_connected_users", "23439854", { unit: "count" }),
            numberField("monthly_follower_growth_rate", "0.0196", { unit: "ratio" }),
          ],
        },
        spread: {
          status: "COLLECTED",
          fields: [
            envelope("interaction_rate", { kind: "structured", data: { value: "112" } }),
            envelope("expected_cpm", { kind: "structured", data: { cpm_21_60: 2969, cpm_60: 3836 } }),
          ],
        },
      },
      profile_complete: true,
      pipeline_complete: true,
    };
    const view = snapshotCreatorView(payload, IDENTITY);
    expect(view.platform).toBe("douyin_xingtu");
    expect(view.creator_type_label).toBe("生活");
    expect(view.content_theme_labels).toEqual(["种草"]);
    expect(view.industry_labels).toEqual(["食品饮料"]);
    expect(view.gender).toBe("2");
    expect(view.followers.value).toBe(1351784);
    expect(view.monthly_deep_users.value).toBe(11580000);
    expect(view.monthly_deep_users.is_approximate).toBe(true);
    expect(view.expected_cpm_21_60.value).toBe(2969);
    expect(view.expected_cpm_60_plus.value).toBe(3836);
  });

  it("maps juxing only onto fields it actually collects and never fakes Xingtu metrics", () => {
    const payload = {
      modules: {
        basic: {
          status: "COLLECTED",
          fields: [
            envelope("nickname", "聚星达人"),
            envelope("content_type_labels", ["母婴亲子"]),
            numberField("followers", "0", { unit: "count" }),
            numberField("monthly_follower_growth_rate", "0.0125", { unit: "ratio" }),
          ],
        },
        spread: {
          status: "COLLECTED",
          fields: [numberField("expected_cpm", "20", { unit: "CNY_per_thousand_impressions" })],
        },
      },
      profile_complete: false,
      pipeline_complete: false,
    };
    const view = snapshotCreatorView(payload, IDENTITY, "kuaishou_juxing");
    expect(view.platform).toBe("kuaishou_juxing");
    expect(view.display_name).toBe("聚星达人");
    // Juxing content types are a different dimension from the Xingtu creator type/industry.
    expect(view.content_theme_labels).toEqual(["母婴亲子"]);
    expect(view.creator_type_label).toBeNull();
    expect(view.industry_labels).toEqual([]);
    expect(view.gender).toBeNull();
    // A real platform zero stays 0.
    expect(view.followers.value).toBe(0);
    expect(view.monthly_follower_growth_rate.value).toBe(0.0125);
    // Xingtu-only metrics must stay absent rather than reinterpreting juxing numbers as them.
    expect(view.monthly_deep_users.value).toBeNull();
    expect(view.monthly_connected_users.value).toBeNull();
    expect(view.interaction_rate.value).toBeNull();
    expect(view.expected_cpm_21_60.value).toBeNull();
    expect(view.expected_cpm_60_plus.value).toBeNull();
    expect(view.expected_cpe_21_60.value).toBeNull();
    expect(view.profile_complete).toBe(false);
    expect(view.pipeline_complete).toBe(false);
  });
});
