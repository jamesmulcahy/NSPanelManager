import { useEffect, useRef, useState } from "react";
import { api, type EntityCandidate, type EntityCandidates, type HomeAssistantLabel, type ImportResult, type RoomLink } from "../../api/client";
import { ErrorBanner, Loading } from "./common";
import { useLoader } from "./useLoader";
import {
  ENTITY_TYPES,
  NO_FILTERS,
  buildImportItems,
  countByRoom,
  displayOrder,
  errorMessage,
  filterCandidates,
  groupByRoom,
  groupState,
  invertSelection,
  isSelectable,
  joinLabelIds,
  nameErrors,
  parseLabelIds,
  pruneSelection,
  roomOptions,
  rowName,
  selectAll,
  selectNone,
  selectedRows,
  toggleGroup,
  typeLabel,
  type Filters,
} from "./sync";

type Meta = { rooms: RoomLink[]; labels: HomeAssistantLabel[]; excluded: string[] };

async function loadMeta(): Promise<Meta> {
  const [links, labels, settings] = await Promise.all([
    api.GET("/rest/v2/home_assistant/room_links"),
    api.GET("/rest/v2/home_assistant/labels"),
    api.GET("/rest/v2/settings"),
  ]);
  if (!links.data) throw new Error(errorMessage(links.error, links.response));
  if (!labels.data) throw new Error(errorMessage(labels.error, labels.response));
  if (!settings.data) throw new Error(errorMessage(settings.error, settings.response));
  return { rooms: links.data, labels: labels.data, excluded: parseLabelIds(settings.data.home_assistant_sync_exclude_labels) };
}

type ImportSummary = { result: ImportResult; perRoom: { roomId: number; roomName: string; count: number }[] };

function GroupCheckbox({ state, label, onChange }: { state: "none" | "some" | "all"; label: string; onChange: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "some";
  }, [state]);
  return <input ref={ref} type="checkbox" className="checkbox checkbox-sm" aria-label={label} checked={state === "all"} onChange={onChange} />;
}

export default function EntitiesStep({ onShowRooms }: { onShowRooms: () => void }) {
  const [includeHidden, setIncludeHidden] = useState(false);
  const [includeImported, setIncludeImported] = useState(false);
  const [includeGroups, setIncludeGroups] = useState(false);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [names, setNames] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [labelDraft, setLabelDraft] = useState<string[] | null>(null);
  const [labelError, setLabelError] = useState<string | null>(null);
  // The import result shows at the top of the step; bring it into view once it arrives.
  const resultRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (summary || importError) resultRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [summary, importError]);

  const meta = useLoader(loadMeta);
  const candidatesLoader = useLoader<EntityCandidates>(async () => {
    const { data, error, response } = await api.GET("/rest/v2/home_assistant/entity_candidates", {
      params: { query: { include_hidden: includeHidden, include_imported: includeImported, include_groups: includeGroups } },
    });
    if (!data) throw new Error(errorMessage(error, response));
    return data;
  }, [includeHidden, includeImported, includeGroups]);

  const loaded = candidatesLoader.state.status === "loaded" ? candidatesLoader.state.data : null;
  const candidates: EntityCandidate[] = loaded?.candidates ?? [];

  // Forget selections of rows that are gone or imported since.
  const [seenCandidates, setSeenCandidates] = useState(loaded);
  if (seenCandidates !== loaded) {
    setSeenCandidates(loaded);
    if (loaded) setSelected(pruneSelection(loaded.candidates, selected));
  }

  const visible = displayOrder(filterCandidates(candidates, filters));
  const groups = groupByRoom(visible);
  const chosen = selectedRows(candidates, selected);
  const hiddenSelected = chosen.filter((row) => !visible.includes(row)).length;
  const problems = nameErrors(candidates, selected, names);
  const metaData = meta.state.status === "loaded" ? meta.state.data : null;
  const roomName = (roomId: number | null) => metaData?.rooms.find((room) => room.room_id === roomId)?.name ?? candidates.find((row) => row.room_id === roomId)?.room_name ?? "another room";
  const linkedRooms = metaData?.rooms.filter((room) => room.link === "linked").length ?? 0;

  async function saveLabels() {
    if (!labelDraft) return;
    setLabelError(null);
    try {
      const { data, error, response } = await api.PATCH("/rest/v2/settings", { body: { home_assistant_sync_exclude_labels: joinLabelIds(labelDraft) } });
      if (!data) {
        setLabelError(`Couldn't save the excluded labels: ${errorMessage(error, response)}`);
        return;
      }
      setLabelDraft(null);
      meta.reload();
      candidatesLoader.reload();
    } catch (caught) {
      setLabelError(errorMessage(caught));
    }
  }

  async function runImport() {
    const items = buildImportItems(candidates, selected, names);
    const perRoom = countByRoom(candidates, selected);
    setImporting(true);
    setImportError(null);
    try {
      const { data, error, response } = await api.POST("/rest/v2/home_assistant/import", { body: { items } });
      setConfirming(false);
      if (!data) {
        setImportError(`Import failed: ${errorMessage(error, response)}`);
        return;
      }
      setSummary({ result: data, perRoom });
      setSelected(new Set());
      candidatesLoader.reload();
    } catch (caught) {
      setConfirming(false);
      setImportError(`Import failed: ${errorMessage(caught)}`);
    } finally {
      setImporting(false);
    }
  }

  if (meta.state.status === "loading") return <Loading text="Loading rooms..." />;
  if (meta.state.status === "error") return <ErrorBanner message={`Couldn't load from Home Assistant: ${meta.state.message}`} onRetry={meta.reload} />;

  if (linkedRooms === 0) {
    return (
      <div className="p-4 bg-base-100 rounded-md shadow-lg">
        <p>
          No rooms are linked to a Home Assistant area yet.{" "}
          <button type="button" className="link" onClick={onShowRooms}>
            Link rooms in step 1
          </button>{" "}
          first.
        </p>
      </div>
    );
  }

  const { labels, excluded } = meta.state.data;
  const labelValue = labelDraft ?? excluded;

  return (
    <div className="flex flex-col gap-4">
      <div ref={resultRef} />
      {summary && (
        <div role="status" className="alert alert-success flex-col items-start">
          <strong>
            Imported {summary.result.created.length} entit{summary.result.created.length === 1 ? "y" : "ies"}
            {summary.result.pages_added > 0 ? `, adding ${summary.result.pages_added} page${summary.result.pages_added === 1 ? "" : "s"}` : ""}.
          </strong>
          <ul>
            {countCreated(summary).map((entry) => (
              <li key={entry.roomId}>
                {entry.roomName}: {entry.count} created
              </li>
            ))}
          </ul>
          {summary.result.skipped.length > 0 && (
            <div>
              Skipped:
              <ul>
                {summary.result.skipped.map((skip) => (
                  <li key={skip.entity_id}>
                    {skip.entity_id}: {skip.reason === "already_imported" ? "already imported" : skip.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button type="button" className="btn btn-sm" onClick={() => setSummary(null)}>
            Dismiss
          </button>
        </div>
      )}
      {importError && <ErrorBanner message={importError} />}

      <div className="p-4 bg-base-100 rounded-md shadow-lg flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="join">
            <button type="button" className="btn btn-sm join-item" onClick={() => setSelected((current) => selectAll(current, visible))}>
              Select all
            </button>
            <button type="button" className="btn btn-sm join-item" onClick={() => setSelected((current) => selectNone(current, visible))}>
              Select none
            </button>
            <button type="button" className="btn btn-sm join-item" onClick={() => setSelected((current) => invertSelection(current, visible))}>
              Invert selection
            </button>
          </div>
          <select
            className="select select-sm"
            aria-label="Filter by type"
            value={filters.type}
            onChange={(event) => setFilters({ ...filters, type: event.target.value as Filters["type"] })}
          >
            <option value="all">All types</option>
            {ENTITY_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
          <select
            className="select select-sm"
            aria-label="Filter by room"
            value={String(filters.roomId)}
            onChange={(event) => setFilters({ ...filters, roomId: event.target.value === "all" ? "all" : Number(event.target.value) })}
          >
            <option value="all">All rooms</option>
            {roomOptions(candidates).map((room) => (
              <option key={room.roomId} value={room.roomId}>
                {room.roomName}
              </option>
            ))}
          </select>
          <span className="ms-auto font-medium" aria-live="polite">
            {chosen.length} selected
            {hiddenSelected > 0 ? ` (${hiddenSelected} hidden by filters)` : ""}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <label className="label cursor-pointer gap-2">
            <input type="checkbox" className="toggle toggle-sm" checked={includeHidden} onChange={(event) => setIncludeHidden(event.target.checked)} />
            <span>Show hidden</span>
          </label>
          <label className="label cursor-pointer gap-2">
            <input type="checkbox" className="toggle toggle-sm" checked={includeImported} onChange={(event) => setIncludeImported(event.target.checked)} />
            <span>Show already imported</span>
          </label>
          <label className="label cursor-pointer gap-2">
            <input type="checkbox" className="toggle toggle-sm" checked={includeGroups} onChange={(event) => setIncludeGroups(event.target.checked)} />
            <span>Show light groups</span>
          </label>
        </div>

        <details>
          <summary className="cursor-pointer">Excluded labels ({excluded.length})</summary>
          <div className="mt-2 flex flex-col gap-2">
            {labels.length === 0 && <p className="text-base-content/50">Home Assistant has no labels.</p>}
            {labels.map((label) => (
              <label key={label.label_id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="checkbox checkbox-sm"
                  checked={labelValue.includes(label.label_id)}
                  onChange={(event) => setLabelDraft(event.target.checked ? [...labelValue, label.label_id] : labelValue.filter((id) => id !== label.label_id))}
                />
                <span>{label.name}</span>
              </label>
            ))}
            {labelValue.filter((id) => !labels.some((label) => label.label_id === id)).map((id) => (
              <p key={id} className="text-sm text-base-content/50">
                Excluded label {id} no longer exists in Home Assistant.
              </p>
            ))}
            {labelError && <ErrorBanner message={labelError} />}
            <div>
              <button type="button" className="btn btn-sm btn-info" disabled={labelDraft === null} onClick={saveLabels}>
                Save excluded labels
              </button>
            </div>
          </div>
        </details>

        {loaded && loaded.entities_without_area > 0 && (
          <p className="text-sm text-base-content/50">
            {loaded.entities_without_area} supported {loaded.entities_without_area === 1 ? "entity has" : "entities have"} no area in Home Assistant — assign an area there to import them.
          </p>
        )}
        {loaded && loaded.excluded_by_label > 0 && (
          <p className="text-sm text-base-content/50">
            {loaded.excluded_by_label} {loaded.excluded_by_label === 1 ? "entity is" : "entities are"} left out because of an excluded label.
          </p>
        )}
      </div>

      {candidatesLoader.state.status === "loading" && <Loading text="Loading entities from Home Assistant..." />}
      {candidatesLoader.state.status === "error" && <ErrorBanner message={`Couldn't load entities: ${candidatesLoader.state.message}`} onRetry={candidatesLoader.reload} />}

      {loaded && groups.length === 0 && <p className="p-4 bg-base-100 rounded-md shadow-lg text-base-content/50">Nothing to import.</p>}

      {loaded && groups.length > 0 && (
        <div className="overflow-x-auto bg-base-100 rounded-md shadow-lg">
          <table className="table table-sm">
            <thead>
              <tr>
                <th className="w-8"></th>
                <th>Name</th>
                <th>Home Assistant entity</th>
                <th>Type</th>
                <th>Room</th>
              </tr>
            </thead>
            {groups.map((group) => (
              <tbody key={group.roomId}>
                <tr className="bg-base-200">
                  <td>
                    <GroupCheckbox state={groupState(selected, group.rows)} label={`Select all in ${group.roomName}`} onChange={() => setSelected((current) => toggleGroup(current, group.rows))} />
                  </td>
                  <th colSpan={4}>
                    {group.roomName} ({group.rows.length})
                  </th>
                </tr>
                {group.rows.map((row) => {
                  const selectable = isSelectable(row);
                  return (
                    <tr key={row.entity_id} className={selectable ? "" : "opacity-60"}>
                      <td>
                        <input
                          type="checkbox"
                          className="checkbox checkbox-sm"
                          aria-label={`Select ${row.entity_id}`}
                          disabled={!selectable}
                          checked={selectable && selected.has(row.entity_id)}
                          onChange={(event) =>
                            setSelected((current) => {
                              const next = new Set(current);
                              if (event.target.checked) next.add(row.entity_id);
                              else next.delete(row.entity_id);
                              return next;
                            })
                          }
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={`input input-sm w-full ${problems[row.entity_id] ? "input-error" : ""}`}
                          aria-label={`Name for ${row.entity_id}`}
                          value={rowName(row, names)}
                          disabled={!selectable}
                          onChange={(event) => setNames({ ...names, [row.entity_id]: event.target.value })}
                        />
                        {problems[row.entity_id] && <span className="text-xs text-error">{problems[row.entity_id]}</span>}
                      </td>
                      <td>
                        <div>{row.entity_id}</div>
                        <div className="text-xs text-base-content/50">{row.ha_name}</div>
                        {(row.hidden || row.is_group) && <div className="text-xs text-base-content/50">{[row.hidden ? "hidden" : "", row.is_group ? "light group" : ""].filter(Boolean).join(", ")}</div>}
                      </td>
                      <td>{typeLabel(row.entity_type)}</td>
                      <td>
                        {row.room_name}
                        {!selectable && <div className="text-xs">Already imported in {roomName(row.already_imported_room_id)}</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            ))}
          </table>
        </div>
      )}

      <div className="flex justify-end p-4 mb-4 bg-base-100 rounded-md shadow-lg">
        <button type="button" className="btn btn-success" disabled={chosen.length === 0 || Object.keys(problems).length > 0 || importing} onClick={() => setConfirming(true)}>
          Import {chosen.length}
        </button>
      </div>

      {confirming && (
        <div className="modal modal-open" role="dialog" aria-modal="true" aria-label="Confirm import" onKeyDown={(event) => event.key === "Escape" && !importing && setConfirming(false)}>
          <div className="modal-box">
            <h3 className="text-lg font-semibold">
              Import {chosen.length} entit{chosen.length === 1 ? "y" : "ies"}?
            </h3>
            <ul className="my-4 flex flex-col gap-1">
              {countByRoom(candidates, selected).map((entry) => (
                <li key={entry.roomId}>
                  {entry.roomName}: {entry.count}
                </li>
              ))}
            </ul>
            <div className="modal-action">
              <button type="button" className="btn btn-neutral" disabled={importing} onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-success" autoFocus disabled={importing} onClick={runImport}>
                {importing && <span className="loading loading-spinner loading-sm"></span>}
                Confirm import
              </button>
            </div>
          </div>
          <div className="modal-backdrop" onClick={() => !importing && setConfirming(false)}></div>
        </div>
      )}
    </div>
  );
}

/** Created entities per room, named from the summary taken when the import started. */
function countCreated(summary: ImportSummary) {
  const counts = new Map<number, number>();
  for (const created of summary.result.created) counts.set(created.room_id, (counts.get(created.room_id) ?? 0) + 1);
  return [...counts].map(([roomId, count]) => ({ roomId, count, roomName: summary.perRoom.find((entry) => entry.roomId === roomId)?.roomName ?? `Room ${roomId}` }));
}
