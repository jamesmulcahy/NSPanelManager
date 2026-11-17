import { useEffect, useState } from "react";
import { api, type HomeAssistantArea, type Room } from "../../api/client";
import { useSettingsStore } from "../../stores/SettingsStore";
import { errorMessage } from "../HomeAssistantSyncPage/sync";

type Choice = "__unset__" | "__none__" | string;
const UNSET: Choice = "__unset__";
const NONE: Choice = "__none__";

const toChoice = (room: Pick<Room, "home_assistant_link" | "home_assistant_area_id">): Choice =>
  room.home_assistant_link === "linked" ? (room.home_assistant_area_id ?? "") : room.home_assistant_link === "none" ? NONE : UNSET;

/**
 * The "Home Assistant area" field of the room page. It saves on its own (PATCH /rest/v2/rooms/<id>),
 * because the rest of the form goes through the older /rest/rooms endpoint.
 */
export default function HomeAssistantAreaField({ roomId }: { roomId: number }) {
  const [room, setRoom] = useState<Room | null>(null);
  const [areas, setAreas] = useState<HomeAssistantArea[] | null>(null);
  const [areasError, setAreasError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [choice, setChoice] = useState<Choice>(UNSET);
  const { status: settingsStatus, settings, fetchData } = useSettingsStore();
  const tokenSet = settings?.home_assistant_token_set ?? false;
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (settingsStatus === "none") fetchData();
  }, [settingsStatus, fetchData]);

  useEffect(() => {
    let current = true;
    api
      .GET("/rest/v2/rooms/{id}", { params: { path: { id: roomId } } })
      .then(({ data, error, response }) => {
        if (!current) return;
        if (data) {
          setRoom(data);
          setChoice(toChoice(data));
        } else setLoadError(errorMessage(error, response));
      })
      .catch((caught) => current && setLoadError(errorMessage(caught)));
    return () => {
      current = false;
    };
  }, [roomId]);

  // Areas come from Home Assistant, so they are only asked for once a token is configured.
  useEffect(() => {
    if (!tokenSet) return;
    let current = true;
    api
      .GET("/rest/v2/home_assistant/areas")
      .then(({ data, error, response }) => {
        if (!current) return;
        if (data) setAreas(data);
        else setAreasError(errorMessage(error, response));
      })
      .catch((caught) => current && setAreasError(errorMessage(caught)));
    return () => {
      current = false;
    };
  }, [tokenSet]);

  if (loadError) {
    return (
      <div role="alert" className="alert alert-error my-2">
        Couldn't load the Home Assistant area: {loadError}
      </div>
    );
  }
  // Without a Home Assistant token the field is of no use, unless the room already carries a link.
  if (!room || (settingsStatus === "loaded" && !tokenSet && room.home_assistant_link === "unset")) return null;

  const missing = room.home_assistant_link === "linked" && areas !== null && !areas.some((area) => area.area_id === room.home_assistant_area_id);
  const dirty = choice !== toChoice(room);

  async function save() {
    if (!room) return;
    setSaving(true);
    setMessage(null);
    const body =
      choice === UNSET ? { home_assistant_link: "unset" as const } : choice === NONE ? { home_assistant_link: "none" as const } : { home_assistant_link: "linked" as const, home_assistant_area_id: choice };
    try {
      const { data, error, response } = await api.PATCH("/rest/v2/rooms/{id}", { params: { path: { id: roomId } }, body });
      if (data) {
        setRoom(data);
        setChoice(toChoice(data));
        setMessage({ kind: "success", text: "Saved the Home Assistant area." });
      } else {
        setMessage({ kind: "error", text: `Couldn't save the Home Assistant area: ${errorMessage(error, response)}` });
      }
    } catch (caught) {
      setMessage({ kind: "error", text: errorMessage(caught) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="my-2 w-full md:ms-1">
      <label htmlFor="home_assistant_area" className="block mb-2 text-sm font-medium">
        Home Assistant area
      </label>
      <div className="flex items-center gap-2">
        <select id="home_assistant_area" className="select bg-base-300 flex-1" value={choice} onChange={(event) => setChoice(event.target.value)}>
          <option value={UNSET}>Not set</option>
          <option value={NONE}>None</option>
          {missing && <option value={room.home_assistant_area_id ?? ""}>{room.home_assistant_area_id} (missing)</option>}
          {(areas ?? []).map((area) => (
            <option key={area.area_id} value={area.area_id} disabled={area.linked_room_id !== null && area.linked_room_id !== roomId}>
              {area.name}
            </option>
          ))}
        </select>
        <button type="button" className="btn btn-info" disabled={!dirty || saving} onClick={save}>
          Save area
        </button>
      </div>
      {missing && <p className="text-sm text-warning mt-1">Area missing in Home Assistant. The room stays linked; pick another area, or choose None.</p>}
      {areasError && <p className="text-sm text-error mt-1">Couldn't load the Home Assistant areas: {areasError}</p>}
      {message && (
        <p role="status" className={`text-sm mt-1 ${message.kind === "error" ? "text-error" : "text-success"}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}
