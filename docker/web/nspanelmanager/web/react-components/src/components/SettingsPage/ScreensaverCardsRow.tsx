import { useState } from "react";
import { useFormContext, useWatch } from "react-hook-form";
import type { SettingsFormValues } from "./form";
import { CARD_TYPES, clampSeconds, DEFAULT_CARD_SECONDS, MAX_CARD_SECONDS, MIN_CARD_SECONDS, parseCards, setCardEnabled, setCardSeconds } from "./screensaverCards";

/** "Also show" rows: a checkbox and a time in seconds per card type, edited into the screensaver_cards setting. */
export function ScreensaverCardsRows() {
  return (
    <fieldset className="mb-2 w-full">
      <legend className="block mb-1 text-sm font-medium">Also show</legend>
      {Object.entries(CARD_TYPES).map(([type, label]) => (
        <CardRow key={type} type={type} label={label} />
      ))}
    </fieldset>
  );
}

function CardRow({ type, label }: { type: string; label: string }) {
  const { control, setValue } = useFormContext<SettingsFormValues>();
  const value = useWatch({ control, name: "screensaver_cards" });
  const card = parseCards(value).find((entry) => entry.type === type);
  const update = (next: string) => setValue("screensaver_cards", next, { shouldDirty: true });

  // What is typed in the time box while it has focus (null: show the stored time). It is written to the setting as soon as
  // it is a valid time, and corrected into the allowed range when it leaves the box.
  const [draft, setDraft] = useState<string | null>(null);
  const seconds = card?.seconds;
  const shown = draft ?? String(seconds ?? DEFAULT_CARD_SECONDS);

  const commit = () => {
    const typed = Number(draft);
    if (card && draft !== null && draft.trim() !== "" && !Number.isNaN(typed)) {
      update(setCardSeconds(value, type, clampSeconds(typed)));
    }
    setDraft(null);
  };

  return (
    <div className="flex items-center gap-4 mb-1">
      <label className="flex items-center gap-2 flex-1 text-sm font-medium cursor-pointer">
        <input
          type="checkbox"
          className="checkbox checkbox-accent checkbox-sm"
          aria-label={`Show ${label.toLowerCase()} card`}
          checked={card !== undefined}
          onChange={(event) => update(setCardEnabled(value, type, event.target.checked, clampSeconds(seconds ?? DEFAULT_CARD_SECONDS)))}
        />
        {label}
      </label>
      <input
        type="number"
        step={1}
        min={MIN_CARD_SECONDS}
        max={MAX_CARD_SECONDS}
        className="input w-32"
        aria-label={`${label} card seconds`}
        disabled={card === undefined}
        value={shown}
        onChange={(event) => {
          setDraft(event.target.value);
          const typed = Number(event.target.value);
          if (card && event.target.value.trim() !== "" && Number.isInteger(typed) && typed >= MIN_CARD_SECONDS && typed <= MAX_CARD_SECONDS) {
            update(setCardSeconds(value, type, typed));
          }
        }}
        onBlur={commit}
      />
      <span className="text-sm opacity-60">seconds</span>
    </div>
  );
}
