import { describe, expect, it } from "vitest";
import { liveMetricList, payloadDisplayName } from "./liveCreator";

const payload = {
  modules: {
    basic: { fields: [{ field_key: "nickname", status: "COLLECTED", value: "美食" }] },
    live: {
      fields: [
        { field_key: "live.room_cnt", status: "COLLECTED", raw_value: "12", value: { kind: "number", amount: "12" }, unit: "count", period_label: "近30天" },
        { field_key: "live.fans_watch_rate", status: "COLLECTED", raw_value: "0.3486", value: { kind: "number", amount: "0.3486" }, unit: "ratio" },
      ],
    },
  },
};

describe("live creator presentation", () => {
  it("reads the shared snapshot display name", () => {
    expect(payloadDisplayName(payload, "fallback")).toBe("美食");
  });

  it("formats platform-native live metrics without inventing missing values", () => {
    const values = liveMetricList("douyin_xingtu", payload);
    expect(values.find((item) => item.key === "live.room_cnt")?.value).toBe("12");
    expect(values.find((item) => item.key === "live.fans_watch_rate")?.value).toBe("34.86%");
    expect(values.find((item) => item.key === "live.acu")?.value).toBe("暂无数据");
  });

  it("keeps juxing live labels distinct from xingtu", () => {
    const values = liveMetricList("kuaishou_juxing", undefined, {
      "live.expect_viewer": { status: "COLLECTED", raw_value: "100", value: { kind: "number", amount: "100" }, unit: "count" },
    });
    expect(values.find((item) => item.key === "live.expect_viewer")?.label).toBe("预期观看人数");
    expect(values.find((item) => item.key === "live.room_cnt")).toBeUndefined();
  });
});
