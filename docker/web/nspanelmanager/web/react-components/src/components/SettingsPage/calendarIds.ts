// The calendar_entity_ids setting: "" (calendar off), "all" (every calendar in Home Assistant, including ones added later),
// or comma-separated calendar.* entity ids.

export const ALL_CALENDARS = "all";

export type CalendarSelection = { all: true } | { all: false; ids: string[] };

/** What the stored string means. Blank entries and repeats are dropped. */
export function parseCalendarIds(value: string | null | undefined): CalendarSelection {
  const text = (value ?? "").trim();
  if (text.toLowerCase() === ALL_CALENDARS) {
    return { all: true };
  }
  const ids: string[] = [];
  for (const part of text.split(",")) {
    const id = part.trim();
    if (id !== "" && !ids.includes(id)) {
      ids.push(id);
    }
  }
  return { all: false, ids };
}

/** The string to store for these calendars. */
export function formatCalendarIds(ids: readonly string[]): string {
  return ids.join(",");
}
