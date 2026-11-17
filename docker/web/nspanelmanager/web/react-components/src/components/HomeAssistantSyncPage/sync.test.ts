import { describe, expect, it } from "vitest";
import {
  ENTITY_NAME_MAX,
  NO_ASSOCIATION,
  NO_FILTERS,
  ROOM_NAME_MAX,
  SKIP,
  applySuggestions,
  areaOwners,
  areasWithoutRoom,
  buildImportItems,
  buildRoomLinks,
  buildRoomsFromAreas,
  choiceToValue,
  countByRoom,
  displayOrder,
  draftErrors,
  errorMessage,
  filterCandidates,
  groupByRoom,
  groupState,
  initialChoices,
  initialDrafts,
  invertSelection,
  joinLabelIds,
  nameErrors,
  parseLabelIds,
  pruneSelection,
  restingAreas,
  roomOptions,
  selectAll,
  selectNone,
  selectedRows,
  toggleGroup,
  validateEntityName,
  validateRoomName,
  valueToChoice,
  withIgnored,
} from "./sync";
import { ROWS, area, candidate, roomLink } from "./testFixtures";

const ids = (rows: { entity_id: string }[]) => rows.map((row) => row.entity_id);
const set = (...values: string[]) => new Set(values);

describe("name validation", () => {
  it("accepts 1 to 30 trimmed characters", () => {
    expect(validateRoomName("Kitchen")).toBeNull();
    expect(validateRoomName("a")).toBeNull();
    expect(validateRoomName("x".repeat(ROOM_NAME_MAX))).toBeNull();
    expect(validateRoomName(`  ${"x".repeat(ROOM_NAME_MAX)}  `)).toBeNull();
  });
  it("rejects empty, blank and too long names", () => {
    expect(validateRoomName("")).toMatch(/Enter a name/);
    expect(validateRoomName("   ")).toMatch(/Enter a name/);
    expect(validateRoomName("x".repeat(ROOM_NAME_MAX + 1))).toMatch(/At most 30/);
  });
  it("applies the entity name limit", () => {
    expect(validateEntityName(" Island ")).toBeNull();
    expect(validateEntityName(" ")).not.toBeNull();
    expect(validateEntityName("x".repeat(ENTITY_NAME_MAX + 1))).not.toBeNull();
  });
});

describe("room choices", () => {
  const rows = [
    roomLink({ room_id: 1, name: "Kitchen", suggested_area_id: "kitchen" }),
    roomLink({ room_id: 2, name: "Foyer", suggested_area_id: null, suggestion_ambiguous: true, suggestion_candidates: ["foyer", "front_foyer"] }),
    roomLink({ room_id: 3, name: "Garden" }),
    roomLink({ room_id: 4, name: "Gym", link: "linked", area_id: "gym", area_name: "Gym" }),
    roomLink({ room_id: 5, name: "Porch", link: "none" }),
  ];

  it("preselects the unambiguous suggestion of unset rooms only", () => {
    expect(initialChoices(rows)).toEqual({ 1: { kind: "area", areaId: "kitchen" }, 2: SKIP, 3: SKIP });
  });

  it("does not give one area to two rooms, or an area another room is linked to", () => {
    const clash = [roomLink({ room_id: 1, name: "A", suggested_area_id: "x" }), roomLink({ room_id: 2, name: "B", suggested_area_id: "x" }), roomLink({ room_id: 3, name: "C", suggested_area_id: "gym" }), rows[3]];
    expect(initialChoices(clash)).toEqual({ 1: { kind: "area", areaId: "x" }, 2: SKIP, 3: SKIP });
  });

  it("applies suggestions to skipped rooms only, leaving other decisions alone", () => {
    const choices = { 1: SKIP, 2: SKIP, 3: NO_ASSOCIATION };
    expect(applySuggestions(rows, choices)).toEqual({ 1: { kind: "area", areaId: "kitchen" }, 2: SKIP, 3: NO_ASSOCIATION });
    expect(applySuggestions(rows, { ...choices, 1: NO_ASSOCIATION })[1]).toEqual(NO_ASSOCIATION);
  });

  it("converts between choices and select values", () => {
    expect(choiceToValue(SKIP)).toBe("");
    expect(valueToChoice("")).toEqual(SKIP);
    expect(valueToChoice(choiceToValue(NO_ASSOCIATION))).toEqual(NO_ASSOCIATION);
    expect(valueToChoice("kitchen")).toEqual({ kind: "area", areaId: "kitchen" });
    expect(choiceToValue({ kind: "area", areaId: "kitchen" })).toBe("kitchen");
  });

  it("builds the PUT body from decisions, leaving skipped rooms out", () => {
    expect(buildRoomLinks(rows, { 1: { kind: "area", areaId: "kitchen" }, 2: SKIP, 3: NO_ASSOCIATION })).toEqual([
      { room_id: 1, link: "linked", area_id: "kitchen" },
      { room_id: 3, link: "none" },
    ]);
    expect(buildRoomLinks(rows, { 1: SKIP, 2: SKIP, 3: SKIP })).toEqual([]);
  });

  it("names who holds an area", () => {
    const areas = [area({ area_id: "gym", name: "Gym", linked_room_id: 4 }), area_("kitchen"), area_("garden")];
    const owners = areaOwners(rows, areas, { 1: { kind: "area", areaId: "kitchen" }, 2: SKIP, 3: SKIP }, 3);
    expect(owners).toEqual({ gym: "Gym", kitchen: "Kitchen" });
    // The room's own choice and its own link are not "held by another room".
    expect(areaOwners(rows, areas, { 1: { kind: "area", areaId: "kitchen" }, 2: SKIP, 3: SKIP }, 1)).toEqual({ gym: "Gym" });
    expect(areaOwners(rows, areas, {}, 4)).toEqual({});
  });
});

function area_(id: string) {
  return area({ area_id: id, name: id });
}

describe("areas without a room", () => {
  const areas = [area({ area_id: "patio", name: "Patio" }), area({ area_id: "gym", name: "Gym", linked_room_id: 4 }), area({ area_id: "attic", name: "Attic", ignored: true }), area({ area_id: "long", name: "A".repeat(40) })];

  it("lists areas with no room that are not ignored", () => {
    expect(areasWithoutRoom(areas).map((a) => a.area_id)).toEqual(["patio", "long"]);
    expect(restingAreas(areas).map((a) => a.area_id)).toEqual(["gym", "attic"]);
  });

  it("starts unchecked, named after the area (cut to 30), and keeps earlier edits", () => {
    const drafts = initialDrafts(areas);
    expect(drafts.patio).toEqual({ areaId: "patio", name: "Patio", checked: false });
    expect(drafts.long.name).toHaveLength(30);
    expect(Object.keys(drafts)).toEqual(["patio", "long"]);
    const edited = initialDrafts(areas, { patio: { areaId: "patio", name: "Deck", checked: true }, gone: { areaId: "gone", name: "x", checked: true } });
    expect(edited.patio.name).toBe("Deck");
    expect(edited.gone).toBeUndefined();
  });

  it("only reports problems of checked drafts", () => {
    const drafts = initialDrafts(areas);
    drafts.patio = { ...drafts.patio, name: "   " };
    expect(draftErrors(areas, drafts)).toEqual({});
    drafts.patio.checked = true;
    expect(draftErrors(areas, drafts)).toEqual({ patio: "Enter a name." });
  });

  it("builds the request with trimmed names for checked areas, in list order", () => {
    const drafts = initialDrafts(areas);
    drafts.long = { ...drafts.long, name: "  Long room ", checked: true };
    drafts.patio = { ...drafts.patio, checked: true };
    expect(buildRoomsFromAreas(areas, drafts)).toEqual([
      { area_id: "patio", friendly_name: "Patio" },
      { area_id: "long", friendly_name: "Long room" },
    ]);
  });

  it("adds to and removes from the ignored set", () => {
    expect(withIgnored(areas, { add: ["patio"] }).sort()).toEqual(["attic", "patio"]);
    expect(withIgnored(areas, { remove: ["attic"] })).toEqual([]);
    expect(withIgnored(areas, { add: ["attic"] })).toEqual(["attic"]);
  });
});

describe("filters", () => {
  it("filters by type and room, together", () => {
    expect(ids(filterCandidates(ROWS, NO_FILTERS))).toHaveLength(6);
    expect(ids(filterCandidates(ROWS, { type: "light", roomId: "all" }))).toEqual(["light.k1", "light.k2", "light.l1", "light.old"]);
    expect(ids(filterCandidates(ROWS, { type: "all", roomId: 2 }))).toEqual(["light.l1", "cover.l", "light.old"]);
    expect(ids(filterCandidates(ROWS, { type: "light", roomId: 2 }))).toEqual(["light.l1", "light.old"]);
    expect(filterCandidates(ROWS, { type: "thermostat", roomId: "all" })).toEqual([]);
  });

  it("lists the rooms that have rows", () => {
    expect(roomOptions(ROWS)).toEqual([
      { roomId: 1, roomName: "Kitchen" },
      { roomId: 2, roomName: "Lounge" },
    ]);
  });
});

describe("selection on visible rows", () => {
  const lights = filterCandidates(ROWS, { type: "light", roomId: "all" });

  it("select all selects visible selectable rows and skips already imported ones", () => {
    expect([...selectAll(set(), lights)].sort()).toEqual(["light.k1", "light.k2", "light.l1"]);
  });

  it("select all keeps selections outside the visible rows", () => {
    expect([...selectAll(set("cover.l"), lights)].sort()).toEqual(["cover.l", "light.k1", "light.k2", "light.l1"]);
  });

  it("select none clears only the visible rows", () => {
    expect([...selectNone(set("light.k1", "cover.l"), lights)]).toEqual(["cover.l"]);
  });

  it("invert flips visible selectable rows only", () => {
    const inverted = invertSelection(set("light.k1", "cover.l"), lights);
    expect([...inverted].sort()).toEqual(["cover.l", "light.k2", "light.l1"]);
    expect(inverted.has("light.old")).toBe(false);
  });

  it("invert twice restores the selection", () => {
    const start = set("light.k1", "cover.l");
    expect(invertSelection(invertSelection(start, lights), lights)).toEqual(start);
  });

  it("does not modify the set it is given", () => {
    const start = set("light.k1");
    selectAll(start, ROWS);
    selectNone(start, ROWS);
    invertSelection(start, ROWS);
    expect([...start]).toEqual(["light.k1"]);
  });
});

describe("room groups", () => {
  const kitchen = ROWS.filter((row) => row.room_id === 1);
  const lounge = ROWS.filter((row) => row.room_id === 2);

  it("groups in order of first appearance", () => {
    const groups = groupByRoom(ROWS);
    expect(groups.map((g) => [g.roomName, g.rows.length])).toEqual([
      ["Kitchen", 3],
      ["Lounge", 3],
    ]);
    expect(ids(displayOrder([ROWS[3], ROWS[0], ROWS[4], ROWS[1]]))).toEqual(["light.l1", "cover.l", "light.k1", "light.k2"]);
  });

  it("has a tri-state over the selectable rows", () => {
    expect(groupState(set(), kitchen)).toBe("none");
    expect(groupState(set("light.k1"), kitchen)).toBe("some");
    expect(groupState(set("light.k1", "light.k2", "media_player.k"), kitchen)).toBe("all");
    // The already imported row doesn't count against "all".
    expect(groupState(set("light.l1", "cover.l"), lounge)).toBe("all");
    expect(groupState(set(), [])).toBe("none");
    expect(groupState(set("light.old"), [ROWS[5]])).toBe("none");
  });

  it("toggles: none or some selects the whole group, all clears it", () => {
    expect([...toggleGroup(set(), kitchen)].sort()).toEqual(["light.k1", "light.k2", "media_player.k"]);
    expect([...toggleGroup(set("light.k1"), kitchen)].sort()).toEqual(["light.k1", "light.k2", "media_player.k"]);
    expect([...toggleGroup(set("light.k1", "light.k2", "media_player.k", "cover.l"), kitchen)]).toEqual(["cover.l"]);
  });

  it("toggles only the rows it is given, so a filtered group leaves its other rows alone", () => {
    const visibleLights = kitchen.filter((row) => row.entity_type === "light");
    expect([...toggleGroup(set("media_player.k"), visibleLights)].sort()).toEqual(["light.k1", "light.k2", "media_player.k"]);
  });
});

describe("import payload", () => {
  it("lists the selected rows in display order, not selection order", () => {
    const selected = set("cover.l", "light.k2", "light.k1");
    expect(buildImportItems(ROWS, selected, {})).toEqual([
      { entity_id: "light.k1", room_id: 1, entity_type: "light", friendly_name: "k1" },
      { entity_id: "light.k2", room_id: 1, entity_type: "light", friendly_name: "k2" },
      { entity_id: "cover.l", room_id: 2, entity_type: "cover", friendly_name: "l" },
    ]);
  });

  it("uses the edited name, trimmed, and leaves out unselectable and unknown rows", () => {
    const items = buildImportItems(ROWS, set("light.k1", "light.old", "light.ghost"), { "light.k1": "  Island  " });
    expect(items).toEqual([{ entity_id: "light.k1", room_id: 1, entity_type: "light", friendly_name: "Island" }]);
  });

  it("groups interleaved rooms together, as the table shows them", () => {
    const mixed = [candidate({ entity_id: "light.a", room_id: 1 }), candidate({ entity_id: "light.b", room_id: 2, room_name: "Lounge" }), candidate({ entity_id: "light.c", room_id: 1 })];
    expect(ids(buildImportItems(mixed, set("light.a", "light.b", "light.c"), {}))).toEqual(["light.a", "light.c", "light.b"]);
  });

  it("flags empty names of selected rows only", () => {
    expect(nameErrors(ROWS, set("light.k1", "light.k2"), { "light.k1": " ", "light.l1": "" })).toEqual({ "light.k1": "Enter a name." });
  });

  it("counts selected rows per room", () => {
    expect(countByRoom(ROWS, set("light.k1", "light.k2", "cover.l"))).toEqual([
      { roomId: 1, roomName: "Kitchen", count: 2 },
      { roomId: 2, roomName: "Lounge", count: 1 },
    ]);
    expect(selectedRows(ROWS, set())).toEqual([]);
  });

  it("prunes selections of rows that are gone or now imported", () => {
    expect([...pruneSelection(ROWS, set("light.k1", "light.old", "light.ghost"))]).toEqual(["light.k1"]);
  });
});

describe("labels and errors", () => {
  it("parses and joins the comma-separated label ids", () => {
    expect(parseLabelIds("a, b,,c ")).toEqual(["a", "b", "c"]);
    expect(parseLabelIds("")).toEqual([]);
    expect(parseLabelIds(null)).toEqual([]);
    expect(joinLabelIds(["a", "b"])).toBe("a,b");
  });

  it("takes the message from the server's body", () => {
    expect(errorMessage({ detail: "Home Assistant is unreachable" }, { status: 502 })).toBe("Home Assistant is unreachable");
    expect(errorMessage({ message: "nope" })).toBe("nope");
    expect(errorMessage({ friendly_name: ["Too long."] })).toBe("friendly_name: Too long.");
    expect(errorMessage(undefined, { status: 500 })).toBe("HTTP 500");
    expect(errorMessage(new TypeError("Failed to fetch"))).toBe("Failed to fetch");
  });
});
