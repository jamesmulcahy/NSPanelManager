import { useState } from "react";
import { api, type HomeAssistantArea, type RoomLink } from "../../api/client";
import { ErrorBanner, Loading } from "./common";
import { useLoader } from "./useLoader";
import {
  ROOM_NAME_MAX,
  applySuggestions,
  areaOwners,
  areasWithoutRoom,
  buildRoomLinks,
  buildRoomsFromAreas,
  choiceToValue,
  draftErrors,
  errorMessage,
  initialChoices,
  initialDrafts,
  restingAreas,
  unsetRooms,
  valueToChoice,
  withIgnored,
  type NewRoomDraft,
  type RoomChoice,
} from "./sync";

type Data = { rows: RoomLink[]; areas: HomeAssistantArea[] };

async function loadRooms(): Promise<Data> {
  const [links, areas] = await Promise.all([api.GET("/rest/v2/home_assistant/room_links"), api.GET("/rest/v2/home_assistant/areas")]);
  if (!links.data) throw new Error(errorMessage(links.error, links.response));
  if (!areas.data) throw new Error(errorMessage(areas.error, areas.response));
  return { rows: links.data, areas: areas.data };
}

export default function RoomsStep({ onRoomsChanged }: { onRoomsChanged?: () => void }) {
  const { state, reload } = useLoader(loadRooms);
  if (state.status === "loading") return <Loading text="Loading rooms and areas from Home Assistant..." />;
  if (state.status === "error") return <ErrorBanner message={`Couldn't load rooms and areas: ${state.message}`} onRetry={reload} />;
  return <RoomsForm data={state.data} reload={reload} onRoomsChanged={onRoomsChanged} />;
}

function RoomsForm({ data, reload, onRoomsChanged }: { data: Data; reload: () => void; onRoomsChanged?: () => void }) {
  const { rows, areas } = data;
  const [choices, setChoices] = useState<Record<number, RoomChoice>>(() => initialChoices(rows));
  const [drafts, setDrafts] = useState<Record<string, NewRoomDraft>>(() => initialDrafts(areas));
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showErrors, setShowErrors] = useState(false);

  // A reload brings new rooms and areas; keep what the user already typed for those still there.
  const [seen, setSeen] = useState(data);
  if (seen !== data) {
    setSeen(data);
    const next = initialChoices(rows);
    for (const row of unsetRooms(rows)) if (row.room_id in choices) next[row.room_id] = choices[row.room_id];
    setChoices(next);
    setDrafts(initialDrafts(areas, drafts));
  }

  const unset = unsetRooms(rows);
  const areaName = (areaId: string) => areas.find((area) => area.area_id === areaId)?.name ?? areaId;
  const decisions = buildRoomLinks(rows, choices);
  const missing = rows.filter((row) => row.link === "linked" && row.area_missing);
  const withoutRoom = areasWithoutRoom(areas);
  const resting = restingAreas(areas);
  const errors = draftErrors(areas, drafts);
  const checkedDrafts = buildRoomsFromAreas(areas, drafts);

  async function run(action: () => Promise<{ ok: boolean; message: string }>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await action();
      if (result.ok) {
        setNotice(result.message);
        reload();
        onRoomsChanged?.();
      } else {
        setError(result.message);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const saveRooms = () =>
    run(async () => {
      const { data: saved, error: failure, response } = await api.PUT("/rest/v2/home_assistant/room_links", { body: decisions });
      return saved ? { ok: true, message: `Saved ${saved.length} room${saved.length === 1 ? "" : "s"}.` } : { ok: false, message: `Couldn't save the rooms: ${errorMessage(failure, response)}` };
    });

  const setIgnored = (ids: string[], message: string) =>
    run(async () => {
      const { data: saved, error: failure, response } = await api.PUT("/rest/v2/home_assistant/ignored_areas", { body: { area_ids: ids } });
      return saved ? { ok: true, message } : { ok: false, message: `Couldn't save the ignored areas: ${errorMessage(failure, response)}` };
    });

  const createRooms = () => {
    setShowErrors(true);
    if (Object.keys(errors).length > 0 || checkedDrafts.length === 0) return;
    setShowErrors(false);
    return run(async () => {
      const { data: created, error: failure, response } = await api.POST("/rest/v2/home_assistant/rooms_from_areas", { body: checkedDrafts });
      return created ? { ok: true, message: `Created ${created.length} room${created.length === 1 ? "" : "s"}.` } : { ok: false, message: `Couldn't create the rooms: ${errorMessage(failure, response)}` };
    });
  };

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}
      {notice && (
        <div role="status" className="alert alert-success my-2">
          {notice}
        </div>
      )}

      {missing.length > 0 && (
        <div role="alert" className="alert alert-warning">
          <span>
            Area missing in Home Assistant: {missing.map((row) => `${row.name} (was ${row.area_id})`).join(", ")}. The rooms stay linked; relink them on their room page.
          </span>
        </div>
      )}

      <section className="p-4 bg-base-100 rounded-md shadow-lg">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xl">Rooms without a Home Assistant area</h3>
          <button type="button" className="btn btn-outline btn-sm" disabled={unset.length === 0 || busy} onClick={() => setChoices((current) => applySuggestions(rows, current))}>
            Apply all suggestions
          </button>
        </div>
        {unset.length === 0 ? (
          <p className="text-base-content/70">Every room has been linked or marked as having no association.</p>
        ) : (
          <>
            <ul className="space-y-2">
              {unset.map((row) => {
                const owners = areaOwners(rows, areas, choices, row.room_id);
                const choice = choices[row.room_id] ?? valueToChoice("");
                return (
                  <li key={row.room_id} className="flex flex-wrap items-center gap-2">
                    <span className="w-48 font-medium">{row.name}</span>
                    <select
                      className="select select-bordered select-sm"
                      aria-label={`Area for ${row.name}`}
                      value={choiceToValue(choice)}
                      onChange={(event) => setChoices({ ...choices, [row.room_id]: valueToChoice(event.target.value) })}
                    >
                      <option value="">Skip for now</option>
                      <option value={choiceToValue({ kind: "none" })}>No association</option>
                      {areas.map((area) => (
                        <option key={area.area_id} value={area.area_id} disabled={area.area_id in owners}>
                          {area.area_id in owners ? `${area.name} (used by ${owners[area.area_id]})` : area.name}
                        </option>
                      ))}
                    </select>
                    {row.suggestion_ambiguous && <span className="text-sm text-warning">Could be: {row.suggestion_candidates.map(areaName).join(", ")}</span>}
                  </li>
                );
              })}
            </ul>
            <div className="text-right mt-4">
              <button type="button" className="btn btn-success" disabled={decisions.length === 0 || busy} onClick={saveRooms}>
                Save
              </button>
            </div>
          </>
        )}
      </section>

      <section className="p-4 bg-base-100 rounded-md shadow-lg">
        <h3 className="text-xl mb-2">Home Assistant areas without a room</h3>
        {withoutRoom.length === 0 ? (
          <p className="text-base-content/70">Every area has a room or has been dismissed.</p>
        ) : (
          <>
            <ul className="space-y-2">
              {withoutRoom.map((area) => {
                const draft = drafts[area.area_id] ?? { areaId: area.area_id, name: area.name, checked: false };
                const problem = draft.checked || showErrors ? errors[area.area_id] : undefined;
                return (
                  <li key={area.area_id} className="flex flex-wrap items-center gap-2">
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm"
                      aria-label={`Create a room for ${area.name}`}
                      checked={draft.checked}
                      onChange={(event) => setDrafts({ ...drafts, [area.area_id]: { ...draft, checked: event.target.checked } })}
                    />
                    <input
                      type="text"
                      className={`input input-bordered input-sm ${problem ? "input-error" : ""}`}
                      aria-label={`Room name for ${area.name}`}
                      maxLength={ROOM_NAME_MAX}
                      value={draft.name}
                      onChange={(event) => setDrafts({ ...drafts, [area.area_id]: { ...draft, name: event.target.value } })}
                    />
                    {problem && <span className="text-sm text-error">{problem}</span>}
                    <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setIgnored(withIgnored(areas, { add: [area.area_id] }), `Won't ask about ${area.name} again.`)}>
                      Don't ask again
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="text-right mt-4">
              <button type="button" className="btn btn-success" disabled={checkedDrafts.length === 0 || busy} onClick={createRooms}>
                Create rooms
              </button>
            </div>
          </>
        )}
      </section>

      <details className="p-4 bg-base-100 rounded-md shadow-lg">
        <summary className="cursor-pointer text-xl">Linked / no association / ignored areas ({rows.filter((row) => row.link !== "unset").length + resting.filter((area) => area.ignored).length})</summary>
        <div className="mt-2 space-y-4">
          <div>
            <h4 className="font-medium">Rooms</h4>
            <ul className="space-y-1">
              {rows
                .filter((row) => row.link !== "unset")
                .map((row) => (
                  <li key={row.room_id}>
                    <a className="link" href={`/rooms/${row.room_id}/`}>
                      {row.name}
                    </a>{" "}
                    <span className="text-base-content/70">
                      {row.link === "none" ? "No association" : row.area_missing ? `Area missing in Home Assistant (${row.area_id})` : `Linked to ${row.area_name ?? row.area_id}`}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
          <div>
            <h4 className="font-medium">Ignored areas</h4>
            {resting.filter((area) => area.ignored).length === 0 ? (
              <p className="text-base-content/70">None.</p>
            ) : (
              <ul className="space-y-1">
                {resting
                  .filter((area) => area.ignored)
                  .map((area) => (
                    <li key={area.area_id} className="flex items-center gap-2">
                      <span>{area.name}</span>
                      <button type="button" className="btn btn-ghost btn-xs" disabled={busy} onClick={() => setIgnored(withIgnored(areas, { remove: [area.area_id] }), `${area.name} is offered as a new room again.`)}>
                        Stop ignoring
                      </button>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        </div>
      </details>
    </div>
  );
}
