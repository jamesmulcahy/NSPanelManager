import { describe, expect, it } from "vitest";
import { formatCalendarIds, parseCalendarIds } from "./calendarIds";

describe("parseCalendarIds", () => {
  it("reads blank, null and undefined as no calendars", () => {
    expect(parseCalendarIds("")).toEqual({ all: false, ids: [] });
    expect(parseCalendarIds("  ")).toEqual({ all: false, ids: [] });
    expect(parseCalendarIds(null)).toEqual({ all: false, ids: [] });
    expect(parseCalendarIds(undefined)).toEqual({ all: false, ids: [] });
  });

  it("reads all, however it is written", () => {
    expect(parseCalendarIds("all")).toEqual({ all: true });
    expect(parseCalendarIds(" All ")).toEqual({ all: true });
  });

  it("splits a list, trimming and dropping blanks and repeats", () => {
    expect(parseCalendarIds("calendar.family, calendar.school,,calendar.family ")).toEqual({ all: false, ids: ["calendar.family", "calendar.school"] });
  });

  it("does not take a calendar with all in its id for all", () => {
    expect(parseCalendarIds("calendar.all")).toEqual({ all: false, ids: ["calendar.all"] });
  });
});

describe("formatCalendarIds", () => {
  it("joins with commas", () => {
    expect(formatCalendarIds(["calendar.a", "calendar.b"])).toBe("calendar.a,calendar.b");
    expect(formatCalendarIds([])).toBe("");
  });

  it("round-trips through parseCalendarIds", () => {
    expect(parseCalendarIds(formatCalendarIds(["calendar.a", "calendar.b"]))).toEqual({ all: false, ids: ["calendar.a", "calendar.b"] });
  });
});
