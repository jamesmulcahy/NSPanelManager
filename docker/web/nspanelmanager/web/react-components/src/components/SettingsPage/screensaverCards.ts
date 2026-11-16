// The screensaver_cards setting is "type:seconds" entries, comma-separated: "calendar:10".

export const DEFAULT_CARD_SECONDS = 10;
export const MIN_CARD_SECONDS = 3;
export const MAX_CARD_SECONDS = 300;

// The card types this page has a row for. Other types in the setting are kept as they are.
export const CARD_TYPES = { calendar: "Calendar", energy: "Energy" } as const;

export type ScreensaverCard = { type: string; seconds: number };

/** Entries with a missing or unreadable time get the default; blank entries are dropped. */
export function parseCards(value: string | null | undefined): ScreensaverCard[] {
  const cards: ScreensaverCard[] = [];
  for (const entry of (value ?? "").split(",")) {
    const [rawType = "", rawSeconds = ""] = entry.split(":");
    const type = rawType.trim();
    if (!type) {
      continue;
    }
    const seconds = Number(rawSeconds.trim());
    cards.push({ type, seconds: rawSeconds.trim() !== "" && Number.isInteger(seconds) && seconds > 0 ? seconds : DEFAULT_CARD_SECONDS });
  }
  return cards;
}

export function serializeCards(cards: ScreensaverCard[]): string {
  return cards.map(({ type, seconds }) => `${type}:${seconds}`).join(",");
}

export const clampSeconds = (seconds: number) => Math.min(MAX_CARD_SECONDS, Math.max(MIN_CARD_SECONDS, Math.round(seconds)));

/** Turns a type on (at `seconds`, or its current time) or off, leaving every other entry and the order alone. */
export function setCardEnabled(value: string | null | undefined, type: string, enabled: boolean, seconds = DEFAULT_CARD_SECONDS): string {
  const cards = parseCards(value);
  const has = cards.some((card) => card.type === type);
  if (enabled) {
    return serializeCards(has ? cards : [...cards, { type, seconds }]);
  }
  return serializeCards(cards.filter((card) => card.type !== type));
}

/** Sets the time of a type's first entry, if it has one. */
export function setCardSeconds(value: string | null | undefined, type: string, seconds: number): string {
  let done = false;
  return serializeCards(
    parseCards(value).map((card) => {
      if (card.type === type && !done) {
        done = true;
        return { type, seconds };
      }
      return card;
    }),
  );
}
