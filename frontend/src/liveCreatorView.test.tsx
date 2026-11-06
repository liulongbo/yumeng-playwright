import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { LiveCreatorDetailView } from "./liveCreator";

afterEach(cleanup);

const base = {
  platform: "douyin_xingtu" as const,
  creatorId: "creator-1",
  platformCreatorId: "9104",
  displayName: "示例达人",
  backTo: "/tasks/1",
  backLabel: "返回任务",
  scopeLabel: "本任务直播快照",
};

function legacySnapshot() {
  return {
    modules: {
      basic: { fields: [{ field_key: "nickname", status: "COLLECTED", value: "示例达人" }] },
      live: {
        fields: [
          {
            field_key: "live.room_cnt",
            status: "COLLECTED",
            raw_value: "12",
            value: { kind: "number", amount: "12" },
            unit: "count",
            period_label: "近30天",
          },
        ],
      },
    },
  };
}

function structuredSnapshot() {
  return {
    modules: {
      basic: { fields: [{ field_key: "nickname", status: "COLLECTED", value: "示例达人" }] },
      live: { fields: [] },
      live_overview: {
        fields: [
          {
            field_key: "overview.general",
            status: "COLLECTED",
            value: { kind: "structured", data: { calibres: [] } },
          },
        ],
      },
    },
  };
}

describe("live creator detail compatibility", () => {
  it("keeps the platform-native strip for a snapshot collected before LIVE-03", () => {
    render(
      <MemoryRouter>
        <LiveCreatorDetailView {...base} payload={legacySnapshot()} />
      </MemoryRouter>,
    );
    expect(screen.getByText("直播表现")).toBeTruthy();
    expect(screen.getByText("近期直播场次")).toBeTruthy();
    expect(screen.getByText(/该快照采集于直播详情字段升级之前/)).toBeTruthy();
  });

  it("uses the structured sections once the newer modules exist", () => {
    render(
      <MemoryRouter>
        <LiveCreatorDetailView {...base} payload={structuredSnapshot()} />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/该快照采集于直播详情字段升级之前/)).toBeNull();
    expect(screen.queryByText("直播表现")).toBeNull();
  });
});
