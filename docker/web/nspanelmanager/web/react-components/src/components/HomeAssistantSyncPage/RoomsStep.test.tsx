import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HomeAssistantArea, RoomLink } from "../../api/client";
import { fakeServer, ok, type Handler } from "./fakeServer";
import RoomsStep from "./RoomsStep";
import { area, roomLink } from "./testFixtures";

let rows: RoomLink[];
let areas: HomeAssistantArea[];
let server: ReturnType<typeof fakeServer>;
let overrides: Record<string, Handler>;

function start() {
  server = fakeServer({
    "GET /rest/v2/home_assistant/room_links": () => ok(rows),
    "GET /rest/v2/home_assistant/areas": () => ok(areas),
    ...overrides,
  });
  vi.stubGlobal("fetch", server.fetchMock);
}

beforeEach(() => {
  document.cookie = "csrftoken=token-123";
  overrides = {};
  rows = [
    roomLink({ room_id: 1, name: "Kitchen", suggested_area_id: "kitchen" }),
    roomLink({ room_id: 2, name: "Foyer", suggestion_ambiguous: true, suggestion_candidates: ["foyer", "front_foyer"] }),
    roomLink({ room_id: 3, name: "Garden" }),
    roomLink({ room_id: 4, name: "Gym", link: "linked", area_id: "gym", area_name: "Gym" }),
    roomLink({ room_id: 5, name: "Porch", link: "none" }),
  ];
  areas = [
    area({ area_id: "kitchen", name: "Kitchen" }),
    area({ area_id: "foyer", name: "Foyer" }),
    area({ area_id: "front_foyer", name: "Front Foyer" }),
    area({ area_id: "gym", name: "Gym", linked_room_id: 4 }),
    area({ area_id: "patio", name: "Patio" }),
    area({ area_id: "playroom", name: "Playroom" }),
    area({ area_id: "attic", name: "Attic", ignored: true }),
  ];
});

afterEach(() => vi.unstubAllGlobals());

async function renderStep() {
  start();
  const user = userEvent.setup();
  render(<RoomsStep />);
  await screen.findByLabelText("Area for Kitchen");
  return user;
}

const areaSelect = (room: string) => screen.getByLabelText(`Area for ${room}`) as HTMLSelectElement;

describe("unset rooms", () => {
  it("preselects the suggestion and shows a hint for an ambiguous one", async () => {
    await renderStep();

    expect(areaSelect("Kitchen")).toHaveValue("kitchen");
    expect(areaSelect("Foyer")).toHaveValue("");
    expect(areaSelect("Garden")).toHaveValue("");
    expect(screen.getByText("Could be: Foyer, Front Foyer")).toBeInTheDocument();
    // Linked and "no association" rooms don't get a row here.
    expect(screen.queryByLabelText("Area for Gym")).not.toBeInTheDocument();
  });

  it("disables areas linked to another room, naming it, and areas chosen for another row", async () => {
    const user = await renderStep();

    expect(within(areaSelect("Garden")).getByRole("option", { name: "Gym (used by Gym)" })).toBeDisabled();
    expect(within(areaSelect("Garden")).getByRole("option", { name: "Kitchen (used by Kitchen)" })).toBeDisabled();
    expect(within(areaSelect("Kitchen")).getByRole("option", { name: "Kitchen" })).toBeEnabled();

    await user.selectOptions(areaSelect("Kitchen"), "");
    expect(within(areaSelect("Garden")).getByRole("option", { name: "Kitchen" })).toBeEnabled();
  });

  it("saves every decision in one PUT, leaving skipped rooms out", async () => {
    overrides["PUT /rest/v2/home_assistant/room_links"] = () => ok([{ room_id: 1, link: "linked", area_id: "kitchen" }, { room_id: 3, link: "none", area_id: "" }]);
    const user = await renderStep();

    await user.selectOptions(areaSelect("Garden"), "No association");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(server.calls("PUT", "/rest/v2/home_assistant/room_links")).toHaveLength(1));
    const put = server.calls("PUT", "/rest/v2/home_assistant/room_links")[0];
    expect(put.body).toEqual([
      { room_id: 1, link: "linked", area_id: "kitchen" },
      { room_id: 3, link: "none" },
    ]);
    expect(await screen.findByRole("status")).toHaveTextContent("Saved 2 rooms.");
    // The page reloads its data afterwards.
    await waitFor(() => expect(server.calls("GET", "/rest/v2/home_assistant/room_links").length).toBeGreaterThan(1));
  });

  it("disables Save until a room is decided", async () => {
    const user = await renderStep();
    await user.selectOptions(areaSelect("Kitchen"), "");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("shows the server's message when saving fails", async () => {
    overrides["PUT /rest/v2/home_assistant/room_links"] = () => ok({ detail: 'Home Assistant area "kitchen" can only be linked to one room' }, 400);
    const user = await renderStep();

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent('Couldn\'t save the rooms: Home Assistant area "kitchen" can only be linked to one room');
    expect(areaSelect("Kitchen")).toHaveValue("kitchen");
  });

  it("Apply all suggestions fills the selects and sends nothing", async () => {
    const user = await renderStep();
    await user.selectOptions(areaSelect("Kitchen"), "");
    expect(areaSelect("Kitchen")).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "Apply all suggestions" }));

    expect(areaSelect("Kitchen")).toHaveValue("kitchen");
    expect(areaSelect("Foyer")).toHaveValue("");
    expect(server.requests.filter((request) => request.method !== "GET")).toEqual([]);
  });
});

describe("areas without a room", () => {
  it("lists areas with no room that aren't ignored, unchecked, named after the area", async () => {
    await renderStep();

    expect(screen.getByLabelText("Room name for Patio")).toHaveValue("Patio");
    expect(screen.getByLabelText("Create a room for Patio")).not.toBeChecked();
    expect(screen.getByLabelText("Create a room for Playroom")).not.toBeChecked();
    expect(screen.queryByLabelText("Room name for Attic")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Room name for Gym")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Room name for Patio")).toHaveAttribute("maxlength", "30");
    expect(screen.getByRole("button", { name: "Create rooms" })).toBeDisabled();
  });

  it("creates the checked rooms with their edited, trimmed names", async () => {
    overrides["POST /rest/v2/home_assistant/rooms_from_areas"] = () =>
      ok(
        [
          { room_id: 9, area_id: "patio" },
          { room_id: 10, area_id: "playroom" },
        ],
        201,
      );
    const user = await renderStep();

    await user.click(screen.getByLabelText("Create a room for Patio"));
    await user.click(screen.getByLabelText("Create a room for Playroom"));
    await user.clear(screen.getByLabelText("Room name for Playroom"));
    await user.type(screen.getByLabelText("Room name for Playroom"), "  Kids room ");
    await user.click(screen.getByRole("button", { name: "Create rooms" }));

    await waitFor(() => expect(server.calls("POST", "/rest/v2/home_assistant/rooms_from_areas")).toHaveLength(1));
    expect(server.calls("POST", "/rest/v2/home_assistant/rooms_from_areas")[0].body).toEqual([
      { area_id: "patio", friendly_name: "Patio" },
      { area_id: "playroom", friendly_name: "Kids room" },
    ]);
    expect(await screen.findByRole("status")).toHaveTextContent("Created 2 rooms.");
    await waitFor(() => expect(server.calls("GET", "/rest/v2/home_assistant/areas").length).toBeGreaterThan(1));
  });

  it("refuses an empty name and doesn't call the server", async () => {
    const user = await renderStep();

    await user.click(screen.getByLabelText("Create a room for Patio"));
    await user.clear(screen.getByLabelText("Room name for Patio"));

    expect(screen.getByText("Enter a name.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create rooms" }));
    expect(server.calls("POST", "/rest/v2/home_assistant/rooms_from_areas")).toHaveLength(0);
  });

  it("limits the typed name to 30 characters", async () => {
    const user = await renderStep();
    await user.clear(screen.getByLabelText("Room name for Patio"));
    await user.type(screen.getByLabelText("Room name for Patio"), "x".repeat(40));
    expect(screen.getByLabelText("Room name for Patio")).toHaveValue("x".repeat(30));
  });

  it("Don't ask again adds the area to the complete ignored set", async () => {
    overrides["PUT /rest/v2/home_assistant/ignored_areas"] = (request) => ok(request.body);
    const user = await renderStep();

    await user.click(within(screen.getByLabelText("Room name for Playroom").closest("li")!).getByRole("button", { name: "Don't ask again" }));

    await waitFor(() => expect(server.calls("PUT", "/rest/v2/home_assistant/ignored_areas")).toHaveLength(1));
    expect(server.calls("PUT", "/rest/v2/home_assistant/ignored_areas")[0].body).toEqual({ area_ids: ["attic", "playroom"] });
    expect(await screen.findByRole("status")).toHaveTextContent("Won't ask about Playroom again.");
  });

  it("shows a failed create as an error", async () => {
    overrides["POST /rest/v2/home_assistant/rooms_from_areas"] = () => ok({ detail: "Home Assistant area \"patio\" is already linked" }, 400);
    const user = await renderStep();
    await user.click(screen.getByLabelText("Create a room for Patio"));
    await user.click(screen.getByRole("button", { name: "Create rooms" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't create the rooms: Home Assistant area \"patio\" is already linked");
  });
});

describe("the collapsed section", () => {
  it("links to each room page and lets an ignored area be brought back", async () => {
    overrides["PUT /rest/v2/home_assistant/ignored_areas"] = (request) => ok(request.body);
    const user = await renderStep();

    expect(screen.getByText(/Linked \/ no association \/ ignored areas \(3\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Gym" })).toHaveAttribute("href", "/rooms/4/");
    expect(screen.getByRole("link", { name: "Porch" })).toHaveAttribute("href", "/rooms/5/");
    expect(screen.getByRole("link", { name: "Porch" }).closest("li")).toHaveTextContent("No association");

    await user.click(screen.getByRole("button", { name: "Stop ignoring" }));

    await waitFor(() => expect(server.calls("PUT", "/rest/v2/home_assistant/ignored_areas")).toHaveLength(1));
    expect(server.calls("PUT", "/rest/v2/home_assistant/ignored_areas")[0].body).toEqual({ area_ids: [] });
  });

  it("flags a room whose area is missing in Home Assistant", async () => {
    rows[3] = roomLink({ room_id: 4, name: "Gym", link: "linked", area_id: "gym", area_name: null, area_missing: true });
    await renderStep();
    expect(screen.getByRole("alert")).toHaveTextContent("Area missing in Home Assistant: Gym");
  });
});

describe("failures", () => {
  it("shows a Home Assistant failure as an error with the message, not as an empty list", async () => {
    overrides["GET /rest/v2/home_assistant/room_links"] = () => ok({ detail: "Home Assistant is unreachable: connection refused" }, 502);
    start();
    render(<RoomsStep />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Home Assistant is unreachable: connection refused");
    expect(screen.queryByLabelText("Area for Kitchen")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
