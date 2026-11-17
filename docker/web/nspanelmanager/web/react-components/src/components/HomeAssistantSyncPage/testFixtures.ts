import type { EntityCandidate, HomeAssistantArea, RoomLink } from "../../api/client";

export function candidate(overrides: Partial<EntityCandidate> & Pick<EntityCandidate, "entity_id">): EntityCandidate {
  return {
    ha_name: overrides.entity_id,
    suggested_name: overrides.entity_id.split(".")[1],
    entity_type: "light",
    room_id: 1,
    room_name: "Kitchen",
    area_id: "kitchen",
    hidden: false,
    is_group: false,
    labels: [],
    already_imported_room_id: null,
    ...overrides,
  };
}

export function roomLink(overrides: Partial<RoomLink> & Pick<RoomLink, "room_id" | "name">): RoomLink {
  return {
    link: "unset",
    area_id: "",
    area_name: null,
    area_missing: false,
    suggested_area_id: null,
    suggestion_ambiguous: false,
    suggestion_candidates: [],
    ...overrides,
  };
}

export function area(overrides: Partial<HomeAssistantArea> & Pick<HomeAssistantArea, "area_id" | "name">): HomeAssistantArea {
  return { linked_room_id: null, ignored: false, ...overrides };
}

// Rows for the entity tests: two rooms, three types, one already imported.
export const ROWS: EntityCandidate[] = [
  candidate({ entity_id: "light.k1", room_id: 1, room_name: "Kitchen", entity_type: "light" }),
  candidate({ entity_id: "light.k2", room_id: 1, room_name: "Kitchen", entity_type: "light" }),
  candidate({ entity_id: "media_player.k", room_id: 1, room_name: "Kitchen", entity_type: "media_player" }),
  candidate({ entity_id: "light.l1", room_id: 2, room_name: "Lounge", entity_type: "light" }),
  candidate({ entity_id: "cover.l", room_id: 2, room_name: "Lounge", entity_type: "cover" }),
  candidate({ entity_id: "light.old", room_id: 2, room_name: "Lounge", entity_type: "light", already_imported_room_id: 3 }),
];
