/** The reason a new room's name is unusable, or null. The server trims and then checks 1..30 characters. */
function validateRoomName(name) {
	const trimmed = name.trim();
	if (trimmed.length === 0) return "Enter a name.";
	if (trimmed.length > 30) return `At most 30 characters.`;
	return null;
}
function validateEntityName(name) {
	const trimmed = name.trim();
	if (trimmed.length === 0) return "Enter a name.";
	if (trimmed.length > 255) return `At most 255 characters.`;
	return null;
}
var SKIP = { kind: "skip" };
var NO_ASSOCIATION = { kind: "none" };
/** The select value used for a choice: "" skip, "__none__" no association, otherwise the area id. */
var NONE_VALUE = "__none__";
function choiceToValue(choice) {
	return choice.kind === "area" ? choice.areaId : choice.kind === "none" ? NONE_VALUE : "";
}
function valueToChoice(value) {
	return value === "" ? SKIP : value === "__none__" ? NO_ASSOCIATION : {
		kind: "area",
		areaId: value
	};
}
var unsetRooms = (rows) => rows.filter((row) => row.link === "unset");
/**
* Fills each unset room with its unambiguous suggestion. An area is given to one room only (the first
* in list order), and never when another room already holds it; rooms that don't get one keep `base`.
*/
function suggest(rows, base, takenAreas) {
	const next = { ...base };
	const taken = new Set(takenAreas);
	for (const choice of Object.values(base)) if (choice.kind === "area") taken.add(choice.areaId);
	for (const row of unsetRooms(rows)) {
		const suggestion = row.suggested_area_id;
		if (suggestion && !row.suggestion_ambiguous && !taken.has(suggestion) && (next[row.room_id] ?? SKIP).kind === "skip") {
			next[row.room_id] = {
				kind: "area",
				areaId: suggestion
			};
			taken.add(suggestion);
		}
	}
	return next;
}
/** The areas other rooms are already linked to. */
var linkedAreas = (rows) => new Set(rows.filter((row) => row.link === "linked").map((row) => row.area_id));
/** The initial choice of each unset room: its unambiguous suggestion, otherwise skip. */
function initialChoices(rows) {
	const base = {};
	for (const row of unsetRooms(rows)) base[row.room_id] = SKIP;
	return suggest(rows, base, linkedAreas(rows));
}
/** "Apply all suggestions": fills the rooms that are still skipped and have a suggestion. Nothing is saved. */
function applySuggestions(rows, choices) {
	return suggest(rows, choices, linkedAreas(rows));
}
/**
* Areas already chosen for another unset room in this form (or linked to another room on the server).
* Returns area id -> the name of the room that holds it, for rooms other than `roomId`.
*/
function areaOwners(rows, areas, choices, roomId) {
	const owners = {};
	const names = new Map(rows.map((row) => [row.room_id, row.name]));
	for (const area of areas) if (area.linked_room_id !== null && area.linked_room_id !== roomId) owners[area.area_id] = names.get(area.linked_room_id) ?? "another room";
	for (const row of unsetRooms(rows)) {
		const choice = choices[row.room_id];
		if (row.room_id !== roomId && choice?.kind === "area" && !(choice.areaId in owners)) owners[choice.areaId] = row.name;
	}
	return owners;
}
/** The PUT room_links body: one entry per unset room that was decided; skipped rooms are left out. */
function buildRoomLinks(rows, choices) {
	const updates = [];
	for (const row of unsetRooms(rows)) {
		const choice = choices[row.room_id] ?? SKIP;
		if (choice.kind === "area") updates.push({
			room_id: row.room_id,
			link: "linked",
			area_id: choice.areaId
		});
		else if (choice.kind === "none") updates.push({
			room_id: row.room_id,
			link: "none"
		});
	}
	return updates;
}
/** Areas that no room uses and that the user hasn't dismissed: candidates for new rooms. */
var areasWithoutRoom = (areas) => areas.filter((area) => area.linked_room_id === null && !area.ignored);
/** Areas shown in the read-only section: linked to a room, or ignored. */
var restingAreas = (areas) => areas.filter((area) => area.linked_room_id !== null || area.ignored);
/** The new ignored set after adding (or removing) areas. */
function withIgnored(areas, change) {
	const ids = new Set(areas.filter((area) => area.ignored).map((area) => area.area_id));
	for (const id of change.add ?? []) ids.add(id);
	for (const id of change.remove ?? []) ids.delete(id);
	return [...ids];
}
/** The drafts for the areas without a room: unchecked, named after the area. */
function initialDrafts(areas, previous = {}) {
	const drafts = {};
	for (const area of areasWithoutRoom(areas)) drafts[area.area_id] = previous[area.area_id] ?? {
		areaId: area.area_id,
		name: area.name.slice(0, 30),
		checked: false
	};
	return drafts;
}
/** Problems with the checked drafts, by area id; empty when "Create rooms" may go ahead. */
function draftErrors(areas, drafts) {
	const errors = {};
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
function buildRoomsFromAreas(areas, drafts) {
	return areasWithoutRoom(areas).filter((area) => drafts[area.area_id]?.checked).map((area) => ({
		area_id: area.area_id,
		friendly_name: drafts[area.area_id].name.trim()
	}));
}
var ENTITY_TYPES = [
	{
		value: "light",
		label: "Light"
	},
	{
		value: "cover",
		label: "Cover"
	},
	{
		value: "media_player",
		label: "Media player"
	},
	{
		value: "thermostat",
		label: "Thermostat"
	}
];
var typeLabel = (type) => ENTITY_TYPES.find((item) => item.value === type)?.label ?? type;
var NO_FILTERS = {
	type: "all",
	roomId: "all"
};
/** An already-imported row is shown but can't be selected. */
var isSelectable = (candidate) => candidate.already_imported_room_id === null;
function filterCandidates(candidates, filters) {
	return candidates.filter((candidate) => (filters.type === "all" || candidate.entity_type === filters.type) && (filters.roomId === "all" || candidate.room_id === filters.roomId));
}
/** Selects every selectable visible row; rows outside `visible` keep their state. */
function selectAll(selected, visible) {
	const next = new Set(selected);
	for (const row of visible) if (isSelectable(row)) next.add(row.entity_id);
	return next;
}
/** Clears the visible rows; rows outside `visible` keep their state. */
function selectNone(selected, visible) {
	const next = new Set(selected);
	for (const row of visible) next.delete(row.entity_id);
	return next;
}
/** Flips every selectable visible row; rows outside `visible` keep their state. */
function invertSelection(selected, visible) {
	const next = new Set(selected);
	for (const row of visible) {
		if (!isSelectable(row)) continue;
		if (next.has(row.entity_id)) next.delete(row.entity_id);
		else next.add(row.entity_id);
	}
	return next;
}
/** The tri-state of a group checkbox, over the group's selectable rows. A group with none is "none". */
function groupState(selected, rows) {
	const selectable = rows.filter(isSelectable);
	if (selectable.length === 0) return "none";
	const count = selectable.filter((row) => selected.has(row.entity_id)).length;
	return count === 0 ? "none" : count === selectable.length ? "all" : "some";
}
/** Clicking a group checkbox: everything selected -> clear the group; otherwise select the whole group. */
function toggleGroup(selected, rows) {
	return groupState(selected, rows) === "all" ? selectNone(selected, rows) : selectAll(selected, rows);
}
/** Groups rows by room, in the order the rooms first appear (the server sorts by room order). */
function groupByRoom(rows) {
	const groups = /* @__PURE__ */ new Map();
	for (const row of rows) {
		let group = groups.get(row.room_id);
		if (!group) {
			group = {
				roomId: row.room_id,
				roomName: row.room_name,
				rows: []
			};
			groups.set(row.room_id, group);
		}
		group.rows.push(row);
	}
	return [...groups.values()];
}
/** The rows in the order the table shows them: group by group. */
var displayOrder = (rows) => groupByRoom(rows).flatMap((group) => group.rows);
/** The distinct rooms of the candidates, for the room filter. */
function roomOptions(candidates) {
	return groupByRoom(candidates).map(({ roomId, roomName }) => ({
		roomId,
		roomName
	}));
}
/** The selected rows (selectable ones only), in display order. */
function selectedRows(candidates, selected) {
	return displayOrder(candidates).filter((row) => isSelectable(row) && selected.has(row.entity_id));
}
/** What the table shows for a row's name: the user's edit, else the suggestion. */
var rowName = (candidate, names) => names[candidate.entity_id] ?? candidate.suggested_name;
/** Selected rows whose name is unusable, by entity id. */
function nameErrors(candidates, selected, names) {
	const errors = {};
	for (const row of selectedRows(candidates, selected)) {
		const error = validateEntityName(rowName(row, names));
		if (error) errors[row.entity_id] = error;
	}
	return errors;
}
/** The POST import body: the selected rows in display order, with their (trimmed) names. */
function buildImportItems(candidates, selected, names) {
	return selectedRows(candidates, selected).map((row) => ({
		entity_id: row.entity_id,
		room_id: row.room_id,
		entity_type: row.entity_type,
		friendly_name: rowName(row, names).trim()
	}));
}
/** Count per room of the selected rows, in display order, for the confirmation. */
function countByRoom(candidates, selected) {
	return groupByRoom(selectedRows(candidates, selected)).map((group) => ({
		roomId: group.roomId,
		roomName: group.roomName,
		count: group.rows.length
	}));
}
/** Drops selections and names of rows that are no longer listed (or are now imported). */
function pruneSelection(candidates, selected) {
	const live = new Set(candidates.filter(isSelectable).map((row) => row.entity_id));
	return new Set([...selected].filter((id) => live.has(id)));
}
/** The exclude-labels setting is a comma-separated list of label ids. */
function parseLabelIds(value) {
	return (value ?? "").split(",").map((id) => id.trim()).filter((id) => id.length > 0);
}
var joinLabelIds = (ids) => ids.join(",");
/** The message of a failed call: the server's {"detail"}, else a generic HTTP message. */
function errorMessage(error, response) {
	if (error && typeof error === "object") {
		const body = error;
		if (typeof body.detail === "string") return body.detail;
		if (typeof body.message === "string") return body.message;
		const first = Object.entries(body).find(([, value]) => Array.isArray(value) && typeof value[0] === "string");
		if (first) return `${first[0]}: ${first[1][0]}`;
	}
	return response ? `HTTP ${response.status}` : error instanceof Error ? error.message : String(error);
}
//#endregion
export { selectedRows as A, parseLabelIds as C, rowName as D, roomOptions as E, withIgnored as F, typeLabel as M, unsetRooms as N, selectAll as O, valueToChoice as P, nameErrors as S, restingAreas as T, initialChoices as _, areasWithoutRoom as a, isSelectable as b, buildRoomsFromAreas as c, displayOrder as d, draftErrors as f, groupState as g, groupByRoom as h, areaOwners as i, toggleGroup as j, selectNone as k, choiceToValue as l, filterCandidates as m, NO_FILTERS as n, buildImportItems as o, errorMessage as p, applySuggestions as r, buildRoomLinks as s, ENTITY_TYPES as t, countByRoom as u, initialDrafts as v, pruneSelection as w, joinLabelIds as x, invertSelection as y };
