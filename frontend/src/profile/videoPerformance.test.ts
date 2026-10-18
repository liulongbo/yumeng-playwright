/**
 * `buildVideoItems` 只做「观测行 → 展示项」的归一化，不推测缺失值、不构造地址。
 *
 * 这里覆盖最容易出错的三处：数字既可能是 JSON 数字也可能是数字字符串；作品 id 有三级回落；
 * 封面状态与已入库对象 id 必须原样带过，且只接受 http(s) 的作品链接。
 */
import { describe, expect, it } from "vitest";
import { buildVideoItems } from "./videoPerformance";
import type { CreatorVideoObservation } from "../types";

function row(overrides: Partial<CreatorVideoObservation> = {}): CreatorVideoObservation {
  return {
    module_key: "recent_video_performance",
    position: 0,
    content_id: null,
    platform_item_id: null,
    platform_video_id: null,
    platform_author_id: null,
    title: null,
    subtitle: null,
    published_at: null,
    published_raw: null,
    play_count: null,
    like_count: null,
    comment_count: null,
    favorite_count: null,
    share_count: null,
    cover_source_uri: null,
    cover_object_id: null,
    cover_status: "NOT_PROVIDED",
    work_url: null,
    field_statuses: {},
    observed_at: "2026-10-16T01:43:32Z",
    ...overrides,
  };
}

describe("buildVideoItems", () => {
  it("accepts both JSON numbers and numeric strings for the counts", () => {
    const items = buildVideoItems([
      row({ play_count: "515348" }),
      row({ play_count: 24642 }),
    ]);
    expect(items.map((item) => item.play)).toEqual([515348, 24642]);
    // 平台未返回该字段时保持 null，不把缺失当成 0。
    expect(buildVideoItems([row({ play_count: null })])[0].play).toBeNull();
  });

  it("falls back platform_item_id → content_id → position-N", () => {
    const items = buildVideoItems([
      row({ platform_item_id: "7692029874500553679", content_id: "content-1" }),
      row({ platform_item_id: null, content_id: "content-2" }),
      row({ platform_item_id: null, content_id: null }),
    ]);
    expect(items.map((item) => item.id)).toEqual([
      "7692029874500553679",
      "content-2",
      "position-2",
    ]);
  });

  it("rejects a work link that is not http(s), including the opaque platform cover key", () => {
    const items = buildVideoItems([
      row({ work_url: "https://www.iesdouyin.com/share/video/7692029874500553679/" }),
      row({ work_url: "tos-cn-i-0813c001/osvAy123" }),
      row({ work_url: null }),
    ]);
    expect(items.map((item) => item.url)).toEqual([
      "https://www.iesdouyin.com/share/video/7692029874500553679/",
      null,
      null,
    ]);
  });

  it("carries cover_status and cover_object_id through and never infers a cover", () => {
    const items = buildVideoItems([
      row({ cover_status: "STORED", cover_object_id: "cover/task-uuid/sha256" }),
      row({ cover_status: "UNRESOLVED", cover_source_uri: "tos-cn-i-0813c001/osvAy123", cover_object_id: null }),
      row({ cover_status: "NOT_PROVIDED", cover_source_uri: null, cover_object_id: null }),
      // 形状异常时的保守降级：不认识的取值按「平台未提供」处理，而不是当成已入库。
      row({ cover_status: "SOMETHING_ELSE" as CreatorVideoObservation["cover_status"], cover_object_id: "cover/x" }),
    ]);
    expect(items[0].cover).toEqual({ objectId: "cover/task-uuid/sha256", status: "STORED" });
    expect(items[1].cover).toEqual({ objectId: null, status: "UNRESOLVED" });
    expect(items[2].cover).toEqual({ objectId: null, status: "NOT_PROVIDED" });
    expect(items[3].cover).toEqual({ objectId: "cover/x", status: "NOT_PROVIDED" });
  });

  it("prefers published_at, then published_raw, then the existing dash fallback", () => {
    const iso = buildVideoItems([row({ published_at: "2026-10-02T11:24:27Z", published_raw: "2026-10-02" })]);
    expect(iso[0].date).toContain("2026");
    expect(iso[0].date).not.toBe("—");
    const raw = buildVideoItems([row({ published_at: null, published_raw: "2026-10-02" })]);
    expect(raw[0].date).toBe("2026-10-02");
    const empty = buildVideoItems([row({ published_at: null, published_raw: null })]);
    expect(empty[0].date).toBe("—");
  });

  it("degrades a missing title and a missing page instead of throwing", () => {
    expect(buildVideoItems([row({ title: null })])[0].title).toBe("平台未返回标题");
    expect(buildVideoItems(null)).toEqual([]);
    expect(buildVideoItems(undefined)).toEqual([]);
  });
});
