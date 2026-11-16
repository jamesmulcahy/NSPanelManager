import { useEffect, useState } from "react";
import { Controller, useFormContext } from "react-hook-form";
import Select, { components, type ClassNamesConfig, type GroupBase, type MultiValueRemoveProps } from "react-select";
import { typedFields } from "../common/typedFields";
import { ALL_CALENDARS, formatCalendarIds, parseCalendarIds } from "./calendarIds";
import type { SettingsFormValues } from "./form";

const { TextInput } = typedFields<SettingsFormValues>();

type CalendarOption = { value: string; label: string; missing?: boolean };

type Calendars = { status: "loading" } | { status: "failed" } | { status: "loaded"; options: CalendarOption[] };

const FILTER = encodeURIComponent(JSON.stringify({ type: ["calendar"] }));

/** The calendar entities Home Assistant has, with their friendly names. Fails when the manager can't get them. */
function useHomeAssistantCalendars(): Calendars {
  const [calendars, setCalendars] = useState<Calendars>({ status: "loading" });
  useEffect(() => {
    const abort = new AbortController();
    (async () => {
      try {
        const response = await fetch(`/rest/home_assistant/entities?filter=${FILTER}`, { credentials: "same-origin", signal: abort.signal });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        const items: unknown = data?.items;
        // The manager answers 200 with "errors" and no items when Home Assistant is unreachable or refuses it.
        if (!Array.isArray(items) || (items.length === 0 && Array.isArray(data.errors) && data.errors.length > 0)) {
          throw new Error("No calendars returned");
        }
        const options = items
          .filter((item): item is { item_id: string; label?: string } => typeof item?.item_id === "string")
          .map((item) => ({ value: item.item_id, label: item.label || item.item_id }))
          .sort((a, b) => a.label.localeCompare(b.label));
        setCalendars({ status: "loaded", options });
      } catch {
        if (!abort.signal.aborted) {
          setCalendars({ status: "failed" });
        }
      }
    })();
    return () => abort.abort();
  }, []);
  return calendars;
}

/** react-select labels the remove button from the rendered label, which here is an element, so label it from the option. */
function RemoveButton(props: MultiValueRemoveProps<CalendarOption, true>) {
  return <components.MultiValueRemove {...props} innerProps={{ ...props.innerProps, "aria-label": `Remove ${props.data.label}` }} />;
}

const classNames: ClassNamesConfig<CalendarOption, true, GroupBase<CalendarOption>> = {
  control: (state) => `${state.isFocused ? "border" : "border-0"} border-accent p-2.5 text-sm rounded-box bg-base-300 rounded-md`,
  menu: () => "bg-base-300 p-2.5 rounded-box",
  option: (state) => `p-1 ${state.isSelected || state.isFocused ? "bg-primary/20 rounded-sm" : ""}`,
  multiValue: (state) => `flex items-center gap-1 rounded-md px-2 py-0.5 mr-1 ${state.data.missing ? "bg-warning/30" : "bg-primary/20"}`,
  multiValueRemove: () => "cursor-pointer px-1 rounded-sm hover:bg-base-100",
  valueContainer: () => "gap-1",
  placeholder: () => "opacity-60",
};

/**
 * The calendar_entity_ids setting: every calendar, or a choice from the ones Home Assistant has. Saved ids that Home
 * Assistant no longer has stay, shown as missing, until they are removed. When the calendars can't be loaded it is
 * the comma-separated text field, so that the setting can still be edited.
 */
export function CalendarPicker() {
  const calendars = useHomeAssistantCalendars();
  if (calendars.status === "failed") {
    return (
      <TextInput
        name="calendar_entity_ids"
        label="Calendars"
        hint={`Couldn't load the calendars from Home Assistant. Enter calendar entities, comma-separated, or "${ALL_CALENDARS}" for every calendar. Blank turns the calendar off.`}
        placeholder="calendar.family, calendar.school"
      />
    );
  }
  return <CalendarChoice calendars={calendars} />;
}

function CalendarChoice({ calendars }: { calendars: Exclude<Calendars, { status: "failed" }> }) {
  const { control } = useFormContext<SettingsFormValues>();
  // What was chosen before All was picked, to come back to.
  const [remembered, setRemembered] = useState<string[]>([]);
  return (
    <Controller
      control={control}
      name="calendar_entity_ids"
      render={({ field, fieldState }) => {
        const selection = parseCalendarIds(field.value);
        const known = calendars.status === "loaded" ? calendars.options : [];
        const chosen: CalendarOption[] = selection.all
          ? []
          : selection.ids.map((id) => known.find((option) => option.value === id) ?? { value: id, label: id, missing: calendars.status === "loaded" });
        const missing = chosen.filter((option) => option.missing);
        const chooseAll = () => {
          if (!selection.all) {
            setRemembered(selection.ids);
          }
          field.onChange(ALL_CALENDARS);
        };
        const chooseSome = () => field.onChange(formatCalendarIds(remembered));
        return (
          <fieldset className="mb-2 w-full">
            <legend className="block mb-1 text-sm font-medium">Calendars</legend>
            <div className="flex flex-wrap border border-neutral rounded-lg mb-2">
              <label className="flex items-center gap-2 flex-1 px-3 py-3 text-sm font-medium cursor-pointer">
                <input type="radio" className="radio radio-accent radio-sm" name="calendar_mode" checked={selection.all} onChange={chooseAll} />
                All calendars
              </label>
              <label className="flex items-center gap-2 flex-1 px-3 py-3 text-sm font-medium cursor-pointer">
                <input type="radio" className="radio radio-accent radio-sm" name="calendar_mode" checked={!selection.all} onChange={chooseSome} />
                Choose calendars
              </label>
            </div>
            {selection.all ? (
              <p className="mt-1 text-sm opacity-60">Every calendar in Home Assistant, including ones added later.</p>
            ) : (
              <>
                <Select<CalendarOption, true>
                  isMulti
                  inputId="calendar_entity_ids"
                  aria-label="Calendar entities"
                  placeholder={calendars.status === "loading" ? "Loading calendars…" : "Choose calendars…"}
                  isLoading={calendars.status === "loading"}
                  options={known}
                  value={chosen}
                  onChange={(next) => field.onChange(formatCalendarIds(next.map((option) => option.value)))}
                  onBlur={field.onBlur}
                  unstyled
                  components={{ MultiValueRemove: RemoveButton }}
                  classNames={classNames}
                  noOptionsMessage={() => "No calendars in Home Assistant"}
                  formatOptionLabel={(option, { context }) =>
                    context === "menu" ? (
                      <>
                        <span>{option.label}</span>
                        <span className="block text-xs opacity-60">{option.value}</span>
                      </>
                    ) : (
                      <span title={option.value}>{option.missing ? `${option.label} (missing)` : option.label}</span>
                    )
                  }
                />
                {missing.length > 0 && (
                  <p className="mt-1 text-sm text-warning">
                    Not in Home Assistant any more: {missing.map((option) => option.value).join(", ")}. They stay saved until you remove them.
                  </p>
                )}
                {!fieldState.error && selection.ids.length === 0 && <p className="mt-1 text-sm opacity-60">Choose at least one calendar. With none, the calendar stays off.</p>}
              </>
            )}
            {fieldState.error?.message && <p className="mt-1 text-sm text-error">{fieldState.error.message}</p>}
          </fieldset>
        );
      }}
    />
  );
}
