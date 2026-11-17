// The logic of the "Sync from Home Assistant" page, kept apart from the components so it can be tested
// without rendering: room name validation, the room decisions of step 1, and the selection, grouping,
// filtering and import payload of step 2.

import type { EntityCandidate, HomeAssistantArea, ImportItem, RoomLink, RoomLinkUpdateRequest } from "../../api/client";

export const ROOM_NAME_MAX = 30;
export const ENTITY_NAME_MAX = 255;

/** The reason a new room's name is unusable, or null. The server trims and then checks 1..30 characters. */
export function validateRoomName(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed.length === 0) return "Enter a name.";
  if (trimmed.length > ROOM_NAME_MAX) return `At most ${ROOM_NAME_MAX} characters.`;
  return null;
}

export function validateEntityName(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed.length === 0) return "Enter a name.";
  if (trimmed.length > ENTITY_NAME_MAX) return `At most ${ENTITY_NAME_MAX} characters.`;
  return null;
}

// ---------------------------------------------------------------------------------------------
// Step 1: rooms

/** What the user chose for an unset room. "skip" leaves it unset; anything else is an area id. */
export type RoomChoice = { kind: "skip" } | { kind: "none" } | { kind: "area"; areaId: string };

export const SKIP: RoomChoice = { kind: "skip" };
export const NO_ASSOCIATION: RoomChoice = { kind: "none" };

/** The select value used for a choice: "" skip, "__none__" no association, otherwise the area id. */
export const NONE_VALUE = "__none__";

export function choiceToValue(choice: RoomChoice): string {
  return choice.kind === "area" ? choice.areaId : choice.kind === "none" ? NONE_VALUE : "";
}

export function valueToChoice(value: string): RoomChoice {
  return value === "" ? SKIP : value === NONE_VALUE ? NO_ASSOCIATION : { kind: "area", areaId: value };
}

export const unsetRooms = (rows: RoomLink[]) => rows.filter((row) => row.link === "unset");

/**
 * Fills each unset room with its unambiguous suggestion. An area is given to one room only (the first
 * in list order), and never when another room already holds it; rooms that don't get one keep `base`.
 */
function suggest(rows: RoomLink[], base: Record<number, RoomChoice>, takenAreas: Set<string>): Record<number, RoomChoice> {
  const next = { ...base };
  const taken = new Set(takenAreas);
  for (const choice of Object.values(base)) if (choice.kind === "area") taken.add(choice.areaId);
  for (const row of unsetRooms(rows)) {
    const suggestion = row.suggested_area_id;
    if (suggestion && !row.suggestion_ambiguous && !taken.has(suggestion) && (next[row.room_id] ?? SKIP).kind === "skip") {
      next[row.room_id] = { kind: "area", areaId: suggestion };
      taken.add(suggestion);
    }
  }
  return next;
}

/** The areas other rooms are already linked to. */
const linkedAreas = (rows: RoomLink[]) => new Set(rows.filter((row) => row.link === "linked").map((row) => row.area_id));

/** The initial choice of each unset room: its unambiguous suggestion, otherwise skip. */
export function initialChoices(rows: RoomLink[]): Record<number, RoomChoice> {
  const base: Record<number, RoomChoice> = {};
  for (const row of unsetRooms(rows)) base[row.room_id] = SKIP;
  return suggest(rows, base, linkedAreas(rows));
}

/** "Apply all suggestions": fills the rooms that are still skipped and have a suggestion. Nothing is saved. */
export function applySuggestions(rows: RoomLink[], choices: Record<number, RoomChoice>): Record<number, RoomChoice> {
  return suggest(rows, choices, linkedAreas(rows));
}

/**
 * Areas already chosen for another unset room in this form (or linked to another room on the server).
 * Returns area id -> the name of the room that holds it, for rooms other than `roomId`.
 */
export function areaOwners(rows: RoomLink[], areas: HomeAssistantArea[], choices: Record<number, RoomChoice>, roomId: number): Record<string, string> {
  const owners: Record<string, string> = {};
  const names = new Map(rows.map((row) => [row.room_id, row.name]));
  for (const area of areas) {
    if (area.linked_room_id !== null && area.linked_room_id !== roomId) owners[area.area_id] = names.get(area.linked_room_id) ?? "another room";
  }
  for (const row of unsetRooms(rows)) {
    const choice = choices[row.room_id];
    if (row.room_id !== roomId && choice?.kind === "area" && !(choice.areaId in owners)) owners[choice.areaId] = row.name;
  }
  return owners;
}

/** The PUT room_links body: one entry per unset room that was decided; skipped rooms are left out. */
export function buildRoomLinks(rows: RoomLink[], choices: Record<number, RoomChoice>): RoomLinkUpdateRequest[] {
  const updates: RoomLinkUpdateRequest[] = [];
  for (const row of unsetRooms(rows)) {
    const choice = choices[row.room_id] ?? SKIP;
    if (choice.kind === "area") updates.push({ room_id: row.room_id, link: "linked", area_id: choice.areaId });
    else if (choice.kind === "none") updates.push({ room_id: row.room_id, link: "none" });
  }
  return updates;
}

/** Areas that no room uses and that the user hasn't dismissed: candidates for new rooms. */
export const areasWithoutRoom = (areas: HomeAssistantArea[]) => areas.filter((area) => area.linked_room_id === null && !area.ignored);

export const ignoredAreas = (areas: HomeAssistantArea[]) => areas.filter((area) => area.ignored && area.linked_room_id === null);

/** Areas shown in the read-only section: linked to a room, or ignored. */
export const restingAreas = (areas: HomeAssistantArea[]) => areas.filter((area) => area.linked_room_id !== null || area.ignored);

/** The new ignored set after adding (or removing) areas. */
export function withIgnored(areas: HomeAssistantArea[], change: { add?: string[]; remove?: string[] }): string[] {
  const ids = new Set(areas.filter((area) => area.ignored).map((area) => area.area_id));
  for (const id of change.add ?? []) ids.add(id);
  for (const id of change.remove ?? []) ids.delete(id);
  return [...ids];
}

export type NewRoomDraft = { areaId: string; name: string; checked: boolean };

/** The drafts for the areas without a room: unchecked, named after the area. */
export function initialDrafts(areas: HomeAssistantArea[], previous: Record<string, NewRoomDraft> = {}): Record<string, NewRoomDraft> {
  const drafts: Record<string, NewRoomDraft> = {};
  for (const area of areasWithoutRoom(areas)) {
    drafts[area.area_id] = previous[area.area_id] ?? { areaId: area.area_id, name: area.name.slice(0, ROOM_NAME_MAX), checked: false };
  }
  return drafts;
}

/** Problems with the checked drafts, by area id; empty when "Create rooms" may go ahead. */
export function draftErrors(areas: HomeAssistantArea[], drafts: Record<string, NewRoomDraft>): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const area of areasWithoutRoom(areas)) {
    const draft = drafts[area.area_id];
    if (draft?.checked) {
      const error = validateRoomName(draft.name);
      if (error) errors[area.area_id] = error;
    }
  }
  return errors;
}

/** The POST rooms_from_areas body, in the order the areas are listed. */
export function buildRoomsFromAreas(areas: HomeAssistantArea[], drafts: Record<string, NewRoomDraft>) {
  return areasWithoutRoom(areas)
    .filter((area) => drafts[area.area_id]?.checked)
    .map((area) => ({ area_id: area.area_id, friendly_name: drafts[area.area_id].name.trim() }));
}

// ---------------------------------------------------------------------------------------------
// Step 2: entities

export type EntityType = EntityCandidate["entity_type"];
export const ENTITY_TYPES: { value: EntityType; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "cover", label: "Cover" },
  { value: "media_player", label: "Media player" },
  { value: "thermostat", label: "Thermostat" },
];
export const typeLabel = (type: EntityType) => ENTITY_TYPES.find((item) => item.value === type)?.label ?? type;

export type Filters = { type: EntityType | "all"; roomId: number | "all" };
export const NO_FILTERS: Filters = { type: "all", roomId: "all" };

/** An already-imported row is shown but can't be selected. */
export const isSelectable = (candidate: EntityCandidate) => candidate.already_imported_room_id === null;

export function filterCandidates(candidates: EntityCandidate[], filters: Filters): EntityCandidate[] {
  return candidates.filter((candidate) => (filters.type === "all" || candidate.entity_type === filters.type) && (filters.roomId === "all" || candidate.room_id === filters.roomId));
}

/** Selects every selectable visible row; rows outside `visible` keep their state. */
export function selectAll(selected: ReadonlySet<string>, visible: EntityCandidate[]): Set<string> {
  const next = new Set(selected);
  for (const row of visible) if (isSelectable(row)) next.add(row.entity_id);
  return next;
}

/** Clears the visible rows; rows outside `visible` keep their state. */
export function selectNone(selected: ReadonlySet<string>, visible: EntityCandidate[]): Set<string> {
  const next = new Set(selected);
  for (const row of visible) next.delete(row.entity_id);
  return next;
}

/** Flips every selectable visible row; rows outside `visible` keep their state. */
export function invertSelection(selected: ReadonlySet<string>, visible: EntityCandidate[]): Set<string> {
  const next = new Set(selected);
  for (const row of visible) {
    if (!isSelectable(row)) continue;
    if (next.has(row.entity_id)) next.delete(row.entity_id);
    else next.add(row.entity_id);
  }
  return next;
}

export type GroupState = "none" | "some" | "all";

/** The tri-state of a group checkbox, over the group's selectable rows. A group with none is "none". */
export function groupState(selected: ReadonlySet<string>, rows: EntityCandidate[]): GroupState {
  const selectable = rows.filter(isSelectable);
  if (selectable.length === 0) return "none";
  const count = selectable.filter((row) => selected.has(row.entity_id)).length;
  return count === 0 ? "none" : count === selectable.length ? "all" : "some";
}

/** Clicking a group checkbox: everything selected -> clear the group; otherwise select the whole group. */
export function toggleGroup(selected: ReadonlySet<string>, rows: EntityCandidate[]): Set<string> {
  return groupState(selected, rows) === "all" ? selectNone(selected, rows) : selectAll(selected, rows);
}

export type RoomGroup = { roomId: number; roomName: string; rows: EntityCandidate[] };

/** Groups rows by room, in the order the rooms first appear (the server sorts by room order). */
export function groupByRoom(rows: EntityCandidate[]): RoomGroup[] {
  const groups = new Map<number, RoomGroup>();
  for (const row of rows) {
    let group = groups.get(row.room_id);
    if (!group) {
      group = { roomId: row.room_id, roomName: row.room_name, rows: [] };
      groups.set(row.room_id, group);
    }
    group.rows.push(row);
  }
  return [...groups.values()];
}

/** The rows in the order the table shows them: group by group. */
export const displayOrder = (rows: EntityCandidate[]) => groupByRoom(rows).flatMap((group) => group.rows);

/** The distinct rooms of the candidates, for the room filter. */
export function roomOptions(candidates: EntityCandidate[]): { roomId: number; roomName: string }[] {
  return groupByRoom(candidates).map(({ roomId, roomName }) => ({ roomId, roomName }));
}

/** The selected rows (selectable ones only), in display order. */
export function selectedRows(candidates: EntityCandidate[], selected: ReadonlySet<string>): EntityCandidate[] {
  return displayOrder(candidates).filter((row) => isSelectable(row) && selected.has(row.entity_id));
}

/** What the table shows for a row's name: the user's edit, else the suggestion. */
export const rowName = (candidate: EntityCandidate, names: Record<string, string>) => names[candidate.entity_id] ?? candidate.suggested_name;

/** Selected rows whose name is unusable, by entity id. */
export function nameErrors(candidates: EntityCandidate[], selected: ReadonlySet<string>, names: Record<string, string>): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const row of selectedRows(candidates, selected)) {
    const error = validateEntityName(rowName(row, names));
    if (error) errors[row.entity_id] = error;
  }
  return errors;
}

/** The POST import body: the selected rows in display order, with their (trimmed) names. */
export function buildImportItems(candidates: EntityCandidate[], selected: ReadonlySet<string>, names: Record<string, string>): ImportItem[] {
  return selectedRows(candidates, selected).map((row) => ({
    entity_id: row.entity_id,
    room_id: row.room_id,
    entity_type: row.entity_type,
    friendly_name: rowName(row, names).trim(),
  }));
}

/** Count per room of the selected rows, in display order, for the confirmation. */
export function countByRoom(candidates: EntityCandidate[], selected: ReadonlySet<string>): { roomId: number; roomName: string; count: number }[] {
  return groupByRoom(selectedRows(candidates, selected)).map((group) => ({ roomId: group.roomId, roomName: group.roomName, count: group.rows.length }));
}

/** Drops selections and names of rows that are no longer listed (or are now imported). */
export function pruneSelection(candidates: EntityCandidate[], selected: ReadonlySet<string>): Set<string> {
  const live = new Set(candidates.filter(isSelectable).map((row) => row.entity_id));
  return new Set([...selected].filter((id) => live.has(id)));
}

/** The exclude-labels setting is a comma-separated list of label ids. */
export function parseLabelIds(value: string | null | undefined): string[] {
  return (value ?? "")
    .split(",")
    .map((id) => id.trim())
    .filter((id) => id.length > 0);
}

export const joinLabelIds = (ids: string[]) => ids.join(",");

/** The message of a failed call: the server's {"detail"}, else a generic HTTP message. */
export function errorMessage(error: unknown, response?: { status: number }): string {
  if (error && typeof error === "object") {
    const body = error as Record<string, unknown>;
    if (typeof body.detail === "string") return body.detail;
    if (typeof body.message === "string") return body.message;
    const first = Object.entries(body).find(([, value]) => Array.isArray(value) && typeof value[0] === "string");
    if (first) return `${first[0]}: ${(first[1] as string[])[0]}`;
  }
  return response ? `HTTP ${response.status}` : error instanceof Error ? error.message : String(error);
}
