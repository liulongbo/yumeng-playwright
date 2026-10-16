/**
 * The provenance drawer (`数据质量与字段来源`).
 *
 * CD-03 需求 4.10 removed the rail's「数据来源」entry, so `pages.tsx` no longer mounts this component.
 * The component and its data (module status, per-field source, field counts) are deliberately kept —
 * only the UI region was removed — and these tests keep the retained component's behaviour covered
 * for whenever it is mounted again.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProvenanceDrawer } from "./audience";
import { indexCatalog } from "../fieldCatalog";
import type { ProfileFieldCatalog } from "../types";

const CATALOG: ProfileFieldCatalog = {
  platform: "douyin_xingtu",
  contract_version: "test",
  modules: [
    {
      key: "basic",
      fields: [
        {
          key: "monthly_deep_users",
          name: "月深度用户数",
          contract_name: "月深度用户数",
          name_source: "contract",
          kind: "number",
          unit: "count",
          period_label: "月",
          empty_values: [],
          missing_source_status: null,
        },
      ],
    },
    {
      key: "commercial",
      fields: [
        {
          key: "cooperation_offers",
          name: "合作形式与报价明细",
          contract_name: "合作形式与报价明细",
          name_source: "contract",
          kind: "structured",
          unit: null,
          period_label: null,
          empty_values: [],
          missing_source_status: null,
        },
      ],
    },
    {
      key: "fans",
      fields: [
        {
          key: "fans_daily_trend",
          name: "近30日粉丝总数趋势",
          contract_name: "近30日连接用户总量趋势",
          name_source: "evidence_correction",
          kind: "structured",
          unit: null,
          period_label: null,
          empty_values: [],
          missing_source_status: null,
        },
      ],
    },
  ],
};

const PAYLOAD = {
  modules: {
    basic: {
      status: "COLLECTED",
      fields: [
        {
          field_key: "monthly_deep_users",
          value: { kind: "number", bound: "approximate", amount: "11580000" },
          raw_value: "1,158w",
          unit: "count",
          period_label: "月",
          status: "COLLECTED",
          observed_at: "2026-10-14T01:56:05Z",
        },
      ],
    },
    commercial: {
      status: "COLLECTED",
      fields: [
        {
          field_key: "cooperation_offers",
          value: { kind: "structured", data: [] },
          status: "COLLECTED",
          observed_at: "2026-10-14T01:56:05Z",
        },
      ],
    },
    fans: {
      status: "COLLECTED",
      fields: [
        {
          field_key: "fans_daily_trend",
          value: { kind: "structured", data: [] },
          status: "COLLECTED",
          observed_at: "2026-10-14T01:56:05Z",
        },
      ],
    },
  },
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ProvenanceDrawer", () => {
  it("lists every field's state, unit and observation time", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ProvenanceDrawer
          open
          onClose={() => undefined}
          payload={PAYLOAD as Record<string, unknown>}
          index={indexCatalog(CATALOG)}
          moduleStatuses={{ basic: "COLLECTED", commercial: "COLLECTED", fans: "COLLECTED" }}
          fieldSources={{}}
          collectedCount={3}
          failedCount={0}
        />
      </QueryClientProvider>,
    );
    const dialog = screen.getByRole("dialog", { name: "数据质量与字段来源" });
    expect(dialog.textContent).toContain("cooperation_offers");
    expect(dialog.textContent).toContain("单位未登记");
    expect(dialog.textContent).toContain("2026-10-14T01:56:05Z");
    // A field whose source is the platform's daily-follower endpoint keeps its corrected name.
    expect(dialog.textContent).toContain("近30日粉丝总数趋势");
    expect(dialog.textContent).not.toContain("近30日连接用户总量趋势");
    expect(dialog.textContent).toContain("名称按实测数据源修正");
  });
});
