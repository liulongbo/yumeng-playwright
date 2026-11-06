import { describe, expect, it } from "vitest";
import {
  audienceData,
  calibreEntries,
  distributionItems,
  fieldsOf,
  introductionText,
  basicText,
  latestData,
  metricText,
  moduleFallback,
  overviewTypes,
  pickCalibre,
  pricingServices,
  roomsData,
  type MetricEnvelope,
} from "./liveDetail";

function structured(data: unknown) {
  return { kind: "structured", data };
}

const payload = {
  creator_scene: "live_square",
  module_fallbacks: {
    live_audience: { snapshot_id: "old", observed_at: "2026-11-04T12:00:00+08:00" },
  },
  modules: {
    basic: {
      fields: [
        { field_key: "nickname", status: "COLLECTED", value: "时尚达人" },
        { field_key: "douyin_id", status: "COLLECTED", value: "34976739532" },
        { field_key: "content_tags", status: "COLLECTED", value: ["语言互动"] },
        { field_key: "introduction", status: "COLLECTED", value: "公开介绍" },
        { field_key: "wechat", status: "COLLECTED", value: "wx_example_001" },
      ],
    },
    live_pricing: {
      fields: [
        {
          field_key: "pricing.services",
          status: "COLLECTED",
          value: structured({
            services: [
              {
                service_label: "品牌营销专场（按天）",
                pricing_mode: "per_day",
                unit: "元/天",
                currency: "CNY",
                price: { status: "COLLECTED", value: "6000", unit: "元/天" },
              },
            ],
          }),
        },
      ],
    },
    live_overview: {
      fields: [
        {
          field_key: "overview.general",
          status: "COLLECTED",
          value: structured({
            live_type: "general",
            calibres: {
              period_30_flow_1_star_0: {
                period: 30,
                period_label: "近30天",
                flow_type: 1,
                excluded_marketing: true,
                only_star_order: false,
                groups: {
                  room: {
                    room_cnt: { status: "COLLECTED", value: "30", unit: "count" },
                    acu: { status: "COLLECTED", value: "270", unit: "count" },
                  },
                  convert: {},
                },
                interpretation: { room_cnt: { status: "COLLECTED", value: "30", unit: "count" } },
              },
              period_90_flow_0_star_1: {
                period: 90,
                period_label: "近90天",
                flow_type: 0,
                excluded_marketing: false,
                only_star_order: true,
                groups: { room: {} },
              },
            },
          }),
        },
      ],
    },
    live_analysis: {
      fields: [
        {
          field_key: "analysis.general.latest",
          status: "COLLECTED",
          value: structured({
            window: 2,
            series: {
              watch_cnt: [
                { index: 0, date: "2026-11-02T22:00:00+08:00", value: "640", status: "COLLECTED" },
                { index: 1, date: "2026-11-01T22:00:00+08:00", value: "0", status: "COLLECTED" },
              ],
            },
          }),
        },
        {
          field_key: "analysis.rooms",
          status: "COLLECTED",
          value: structured({
            rows: [{ room_id: "1", title: "第一场" }],
            pagination: { total_count: 1 },
          }),
        },
      ],
    },
    live_audience: {
      fields: [
        {
          field_key: "audience.general.fans",
          status: "COLLECTED",
          value: structured({
            distributions: {
              gender: {
                type_display: "性别分布",
                total: "48960",
                items: [
                  { key: "男", count: "9588", percent: 19.58 },
                  { key: "女", count: "39372", percent: 80.42 },
                ],
                top10: [],
              },
            },
          }),
        },
      ],
    },
  },
};

describe("live detail presentation", () => {
  it("renders missing reasons and never turns them into zero", () => {
    const missing: MetricEnvelope = {
      status: "NOT_PROVIDED",
      reason: "非星图商单，不做统计",
      raw: "-",
    };
    const zero: MetricEnvelope = { status: "COLLECTED", value: "0", unit: "count", raw: "0" };
    expect(metricText(missing)).toBe("非星图商单，不做统计");
    expect(metricText(zero)).toBe("0");
    expect(metricText({ status: "COLLECTED", value: "0.1392", unit: "ratio" })).toBe("13.92%");
    expect(metricText({ status: "COLLECTED", value: "95", unit: "second" })).toBe("1分35秒");
    expect(metricText({ status: "COLLECTED", range: { min: "20000", max: "200000" } })).toBe(
      "20000 ~ 200000",
    );
    expect(metricText({ status: "COLLECTED", range: { min: "0", max: "0" }, raw: "0" })).toBe("0");
  });

  it("separates live-type and calibre values", () => {
    const overview = fieldsOf(payload, "live_overview")["overview.general"].value as {
      data: Parameters<typeof calibreEntries>[0];
    };
    const entries = calibreEntries(overview.data);
    expect(entries.map((item) => item.key)).toEqual([
      "period_30_flow_1_star_0",
      "period_90_flow_0_star_1",
    ]);
    expect(pickCalibre(overview.data, 30, true, false)?.excluded_marketing).toBe(true);
    expect(pickCalibre(overview.data, 90, false, true)?.only_star_order).toBe(true);
    expect(overviewTypes(payload)).toEqual([{ key: "general", label: "不限" }]);
  });

  it("computes audience shares from platform counts", () => {
    const audience = audienceData(payload, "general", "fans");
    const items = distributionItems(audience, "gender");
    expect(items[0].label).toBe("男");
    expect(items[0].value).toBe(9588);
    expect((items[0].share ?? 0).toFixed(2)).toBe("19.58");
  });

  it("reads pricing, rooms, latest and module fallback", () => {
    expect(pricingServices(payload)[0].service_label).toBe("品牌营销专场（按天）");
    expect(roomsData(payload)?.rows?.[0].title).toBe("第一场");
    expect(latestData(payload, "general")?.series?.watch_cnt?.[0].value).toBe("640");
    expect(moduleFallback(payload, "live_audience")).toContain("2026-11-04");
    expect(moduleFallback(payload, "live_overview")).toBeNull();
    expect(introductionText(payload)).toBe("公开介绍");
    expect(basicText(payload, "wechat")).toBe("wx_example_001");
  });
});
