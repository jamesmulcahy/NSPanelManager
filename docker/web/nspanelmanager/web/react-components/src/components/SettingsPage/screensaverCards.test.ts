import { describe, expect, it } from "vitest";
import { parseCards, serializeCards, setCardEnabled, setCardSeconds } from "./screensaverCards";

describe("parseCards", () => {
  it("reads type:seconds entries", () => {
    expect(parseCards("calendar:15")).toEqual([{ type: "calendar", seconds: 15 }]);
  });

  it("is empty for a blank or missing setting", () => {
    expect(parseCards("")).toEqual([]);
    expect(parseCards(null)).toEqual([]);
    expect(parseCards(" , ")).toEqual([]);
  });

  it("uses 10 seconds when the time is missing or unreadable", () => {
    expect(parseCards("calendar, calendar:, calendar:abc, calendar:0, calendar:1.5").map((card) => card.seconds)).toEqual([10, 10, 10, 10, 10]);
  });

  it("keeps types it does not know and tolerates spaces", () => {
    expect(parseCards(" calendar : 20 , news:7 ")).toEqual([
      { type: "calendar", seconds: 20 },
      { type: "news", seconds: 7 },
    ]);
  });
});

describe("serializeCards", () => {
  it("round trips", () => {
    expect(serializeCards(parseCards("calendar:15,news:7"))).toBe("calendar:15,news:7");
    expect(serializeCards([])).toBe("");
  });
});

describe("setCardEnabled", () => {
  it("adds a type after the others, at the given time", () => {
    expect(setCardEnabled("news:7", "calendar", true, 12)).toBe("news:7,calendar:12");
    expect(setCardEnabled("", "calendar", true)).toBe("calendar:10");
  });

  it("leaves an existing entry alone when turned on", () => {
    expect(setCardEnabled("calendar:30", "calendar", true, 12)).toBe("calendar:30");
  });

  it("removes only that type", () => {
    expect(setCardEnabled("calendar:30,news:7", "calendar", false)).toBe("news:7");
    expect(setCardEnabled("calendar:30", "calendar", false)).toBe("");
  });
});

describe("setCardSeconds", () => {
  it("changes that type's time and keeps the rest", () => {
    expect(setCardSeconds("news:7,calendar:30", "calendar", 45)).toBe("news:7,calendar:45");
  });
});
