import { describe, expect, it } from "vitest";
import {
  countText,
  countUnitText,
  countWanText,
  fieldStatusText,
  isBlank,
  moduleStatusTone,
  numberOrNull,
  parseEmbeddedJson,
  plainDateText,
  rangeText,
  overtakePercentText,
  ratioPercentText,
  shortText,
  tenThousandthsPercentText,
  unixSecondsText,
} from "./format";

/**
 * CD-03 需求 4.4, user-confirmed 2026-10-15: n ≥ 10,000 → 万 (1 decimal); 1,000 ≤ n < 10,000 → k
 * (1 decimal); n < 1,000 → the plain number.  Every case here is on the display layer only.
 */
describe("countUnitText", () => {
  it("renders 万 above ten thousand, in the unit 巨量星图 itself prints", () => {
    expect(countUnitText(23_439_854)).toBe("2,344.0万");
    expect(countUnitText("1351784")).toBe("135.2万");
    expect(countUnitText(14_067_210)).toBe("1,406.7万");
    expect(countUnitText(10_000)).toBe("1.0万");
    expect(countUnitText(9_999_999)).toBe("1,000.0万");
  });

  it("renders k between one thousand and ten thousand", () => {
    expect(countUnitText(9_999)).toBe("10.0k");
    expect(countUnitText(1_000)).toBe("1.0k");
    expect(countUnitText(7_540)).toBe("7.5k");
  });

  it("keeps a plain number below one thousand", () => {
    expect(countUnitText(999)).toBe("999");
    expect(countUnitText(0)).toBe("0");
  });

  it("keeps the platform's approximate marker and the sign", () => {
    expect(countUnitText(11_580_000, { approximate: true })).toBe("≈1,158.0万");
    expect(countUnitText(-2_688_009, { approximate: false })).toBe("-268.8万");
  });

  it("never invents a value for a missing, dashed or non-numeric answer", () => {
    for (const value of [null, undefined, "", "-", "—", "20,000 - 100,000", true]) {
      expect(countUnitText(value)).toBe("—");
    }
  });
});

describe("isBlank", () => {
  it("treats platform empty markers as empty, not zero", () => {
    for (const value of [null, undefined, "", "-", "--", "—", "- ", "[]"]) {
      expect(isBlank(value)).toBe(true);
    }
  });

  it("keeps a real zero and a real value as present", () => {
    expect(isBlank(0)).toBe(false);
    expect(isBlank("0")).toBe(false);
    expect(isBlank({ kind: "number", amount: "0" })).toBe(false);
    expect(isBlank(["游戏"])).toBe(false);
  });

  it("sees through the observation envelope and its data/value/amount leaves", () => {
    expect(isBlank({ kind: "structured", data: {} })).toBe(true);
    expect(isBlank({ kind: "structured", data: "-" })).toBe(true);
    expect(isBlank({ kind: "structured", data: "929620" })).toBe(false);
    expect(isBlank({ kind: "structured", data: { value: null } })).toBe(true);
    expect(isBlank({ kind: "structured", data: { value: 0 } })).toBe(false);
  });
});

describe("numberOrNull", () => {
  it("parses platform numeric strings with separators", () => {
    expect(numberOrNull("1,351,784")).toBe(1351784);
    expect(numberOrNull("929620")).toBe(929620);
    expect(numberOrNull(929620)).toBe(929620);
  });

  it("never turns a range, a dash or a boolean into a number", () => {
    expect(numberOrNull("20,000 - 100,000")).toBeNull();
    expect(numberOrNull("-")).toBeNull();
    expect(numberOrNull("")).toBeNull();
    expect(numberOrNull(true)).toBeNull();
    expect(numberOrNull(null)).toBeNull();
  });
});

describe("countText", () => {
  it("uses thousands separators and marks approximate platform values", () => {
    expect(countText("1351784")).toBe("1,351,784");
    expect(countText("11580000", { approximate: true })).toBe("≈11,580,000");
    expect(countText(null)).toBe("—");
  });
});

describe("ratioPercentText", () => {
  it("scales a registered ratio decimal to a percentage", () => {
    expect(ratioPercentText("0.01969004266000137")).toBe("1.97%");
    expect(ratioPercentText(-0.002416911820995418)).toBe("-0.24%");
  });

  it("does not fabricate a percentage for a non-number", () => {
    expect(ratioPercentText("-")).toBe("—");
  });
});

describe("tenThousandthsPercentText", () => {
  it("reads the platform's 万分比 integer as a percentage", () => {
    expect(tenThousandthsPercentText(196)).toBe("1.96%");
    expect(tenThousandthsPercentText(-24)).toBe("-0.24%");
  });
});

describe("unixSecondsText", () => {
  it("renders a platform unix-seconds string as a local date", () => {
    expect(unixSecondsText("1791942965")).toMatch(/^2026\/10\/1[34]$/);
  });

  it("returns a dash for a missing or nonsensical value", () => {
    expect(unixSecondsText(null)).toBe("—");
    expect(unixSecondsText("-")).toBe("—");
    expect(unixSecondsText("0")).toBe("—");
  });
});

describe("plainDateText", () => {
  it("keeps a platform YYYY-MM-DD date unchanged", () => {
    expect(plainDateText("2026-10-12")).toBe("2026-10-12");
  });

  it("formats an ISO timestamp and passes unknown text through", () => {
    expect(plainDateText("2026-10-14T02:02:10Z")).toMatch(/^2026\/10\/1[34]$/);
    expect(plainDateText("-")).toBe("—");
  });
});

describe("parseEmbeddedJson", () => {
  it("parses the JSON document a platform field returns inside a string", () => {
    expect(parseEmbeddedJson('[{"key":"1916","rate":"1.0","value":"6"}]')).toEqual([
      { key: "1916", rate: "1.0", value: "6" },
    ]);
    expect(parseEmbeddedJson('{"value":"1"}')).toEqual({ value: "1" });
  });

  it("leaves plain text, numbers and broken JSON untouched", () => {
    expect(parseEmbeddedJson("929620")).toBe("929620");
    expect(parseEmbeddedJson("[1,2")).toBe("[1,2");
    expect(parseEmbeddedJson("20,000 - 100,000")).toBe("20,000 - 100,000");
    expect(parseEmbeddedJson(null)).toBeNull();
  });
});

describe("rangeText and shortText", () => {
  it("shows a platform range as-is and an empty range as a dash", () => {
    expect(rangeText("20,000 - 100,000")).toBe("20,000 - 100,000");
    expect(rangeText("0.5% - 1%")).toBe("0.5% - 1%");
    expect(rangeText("-")).toBe("—");
  });

  it("truncates long text but reports a long value as truncated", () => {
    const long = "雨刮器为什么不好用 #汽车知识#说车聊车#行车安全#汽车保养#汽车";
    expect(shortText(long, 10)).toBe("雨刮器为什么不好用 …");
    expect(shortText(long, 200)).toBe(long);
    expect(shortText("")).toBe("—");
  });
});

describe("status labels and tones", () => {
  it("labels every registered observation status in Chinese", () => {
    expect(fieldStatusText("COLLECTED")).toBe("已采集");
    expect(fieldStatusText("NO_DATA")).toBe("平台暂无数据");
    expect(fieldStatusText("NOT_ATTEMPTED")).toBe("本次未采集");
    expect(fieldStatusText("FAILED")).toBe("采集失败");
    expect(fieldStatusText(undefined)).toBe("暂无数据");
  });

  it("maps a module status to a tone", () => {
    expect(moduleStatusTone("COLLECTED")).toBe("ok");
    expect(moduleStatusTone("NOT_ATTEMPTED")).toBe("warn");
    expect(moduleStatusTone("FAILED")).toBe("bad");
  });
});

/**
 * CD-04 需求 4.1/4.2, user-confirmed 2026-10-15: n ≥ 10,000 → w (1 decimal, rounded);
 * 1,000 ≤ n < 10,000 → k; below → the plain number.  Distinct from `countUnitText` only in the
 * top-tier spelling (`w` here, `万` on the identity rail).
 */
describe("countWanText", () => {
  it("renders w at or above ten thousand", () => {
    expect(countWanText(929_620)).toBe("93.0w");
    expect(countWanText("862850")).toBe("86.3w");
    expect(countWanText(1_944_275)).toBe("194.4w");
    expect(countWanText(54_000)).toBe("5.4w");
    expect(countWanText(11_000)).toBe("1.1w");
    expect(countWanText(10_000)).toBe("1.0w");
  });

  it("renders k between one thousand and ten thousand", () => {
    expect(countWanText(9_999)).toBe("10.0k");
    expect(countWanText(1_000)).toBe("1.0k");
    expect(countWanText(3_000)).toBe("3.0k");
  });

  it("keeps a plain number below one thousand and never invents a value", () => {
    expect(countWanText(999)).toBe("999");
    expect(countWanText(0)).toBe("0");
    for (const value of [null, undefined, "", "-", "500以下", true]) {
      expect(countWanText(value)).toBe("—");
    }
  });

  it("keeps the platform approximate marker", () => {
    expect(countWanText(12_345, { approximate: true })).toBe("≈1.2w");
  });
});

/**
 * CD-04 需求 4.1: the platform `overtake` integer is a 万分比 (7493 → 74.93%) and means
 * 「优于同类型达人 X%」 — the direction is 「优于」, confirmed against the live page (CD-02).
 */
describe("overtakePercentText", () => {
  it("converts the stored 万分比 to one-decimal percent", () => {
    expect(overtakePercentText(7493)).toBe("74.9%");
    expect(overtakePercentText(9801)).toBe("98.0%");
    expect(overtakePercentText(9759)).toBe("97.6%");
    expect(overtakePercentText("9989")).toBe("99.9%");
    expect(overtakePercentText(10000)).toBe("100.0%");
  });

  it("never turns a missing reading into 0%", () => {
    for (const value of [null, undefined, "", "-", {}]) {
      expect(overtakePercentText(value)).toBe("—");
    }
  });
});
