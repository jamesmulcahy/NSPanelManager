import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { settingsFixture } from "../SettingsPage/testFixtures";
import { fakeServer, ok } from "./fakeServer";
import HomeAssistantSyncPage from "./HomeAssistantSyncPage";
import { ROWS, area, roomLink } from "./testFixtures";

beforeEach(() => {
  const server = fakeServer({
    "GET /rest/v2/home_assistant/room_links": () => ok([roomLink({ room_id: 1, name: "Kitchen", link: "linked", area_id: "kitchen" }), roomLink({ room_id: 2, name: "Garden" })]),
    "GET /rest/v2/home_assistant/areas": () => ok([area({ area_id: "kitchen", name: "Kitchen", linked_room_id: 1 })]),
    "GET /rest/v2/home_assistant/labels": () => ok([]),
    "GET /rest/v2/settings": () => ok(settingsFixture()),
    "GET /rest/v2/home_assistant/entity_candidates": () => ok({ candidates: ROWS, entities_without_area: 0, excluded_by_label: 0 }),
  });
  vi.stubGlobal("fetch", server.fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe("HomeAssistantSyncPage", () => {
  it("starts on the rooms step and switches to the entities step and back", async () => {
    const user = userEvent.setup();
    render(<HomeAssistantSyncPage />);

    expect(screen.getByRole("tab", { name: "1. Rooms", selected: true })).toBeInTheDocument();
    expect(await screen.findByLabelText("Area for Garden")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "2. Entities" }));
    expect(await screen.findByLabelText("Select light.k1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Area for Garden")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "1. Rooms" }));
    expect(await screen.findByLabelText("Area for Garden")).toBeInTheDocument();
  });
});
