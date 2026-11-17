import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Room } from "../../api/client";
import { useSettingsStore } from "../../stores/SettingsStore";
import { fakeServer, ok, type Handler } from "../HomeAssistantSyncPage/fakeServer";
import { area } from "../HomeAssistantSyncPage/testFixtures";
import HomeAssistantAreaField from "./HomeAssistantAreaField";

let room: Room;
let tokenSet: boolean;
let overrides: Record<string, Handler>;
let server: ReturnType<typeof fakeServer>;

function start() {
  server = fakeServer({
    "GET /rest/v2/rooms/7": () => ok(room),
    "GET /rest/settings": () => ok({ settings: { home_assistant_token_set: tokenSet } }),
    "GET /rest/v2/home_assistant/areas": () => ok([area({ area_id: "kitchen", name: "Kitchen" }), area({ area_id: "gym", name: "Gym", linked_room_id: 3 }), area({ area_id: "loft", name: "Loft", linked_room_id: 7 })]),
    "PATCH /rest/v2/rooms/7": (request) => ok({ ...room, ...(request.body as object) }),
    ...overrides,
  });
  vi.stubGlobal("fetch", server.fetchMock);
}

beforeEach(() => {
  document.cookie = "csrftoken=token-123";
  useSettingsStore.setState({ status: "none", settings: null });
  tokenSet = true;
  overrides = {};
  room = { id: 7, friendly_name: "Office", displayOrder: 1, room_temp_provider: "", room_temp_sensor: "", home_assistant_link: "unset", home_assistant_area_id: "" } as Room;
});

afterEach(() => vi.unstubAllGlobals());

const select = () => screen.getByLabelText("Home Assistant area") as HTMLSelectElement;
const patches = () => server.calls("PATCH", "/rest/v2/rooms/7");

async function renderField() {
  start();
  const user = userEvent.setup();
  render(<HomeAssistantAreaField roomId={7} />);
  await screen.findByLabelText("Home Assistant area");
  await waitFor(() => expect(screen.getByRole("option", { name: "Kitchen" })).toBeInTheDocument());
  return user;
}

describe("HomeAssistantAreaField", () => {
  it("offers Not set, None and the areas, with areas of other rooms disabled", async () => {
    await renderField();

    expect(select()).toHaveValue("__unset__");
    expect(within(select()).getByRole("option", { name: "Not set" })).toBeInTheDocument();
    expect(within(select()).getByRole("option", { name: "None" })).toBeInTheDocument();
    expect(within(select()).getByRole("option", { name: "Gym" })).toBeDisabled();
    expect(within(select()).getByRole("option", { name: "Loft" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Save area" })).toBeDisabled();
  });

  it("links the room to the chosen area with a PATCH", async () => {
    const user = await renderField();

    await user.selectOptions(select(), "Kitchen");
    await user.click(screen.getByRole("button", { name: "Save area" }));

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].body).toEqual({ home_assistant_link: "linked", home_assistant_area_id: "kitchen" });
    expect(await screen.findByRole("status")).toHaveTextContent("Saved the Home Assistant area.");
  });

  it("marks the room as having no association", async () => {
    const user = await renderField();
    await user.selectOptions(select(), "None");
    await user.click(screen.getByRole("button", { name: "Save area" }));
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].body).toEqual({ home_assistant_link: "none" });
  });

  it("sets a linked room back to Not set", async () => {
    room = { ...room, home_assistant_link: "linked", home_assistant_area_id: "loft" };
    const user = await renderField();
    expect(select()).toHaveValue("loft");

    await user.selectOptions(select(), "Not set");
    await user.click(screen.getByRole("button", { name: "Save area" }));

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].body).toEqual({ home_assistant_link: "unset" });
  });

  it("says when the linked area is missing in Home Assistant", async () => {
    room = { ...room, home_assistant_link: "linked", home_assistant_area_id: "attic" };
    await renderField();

    expect(screen.getByText(/Area missing in Home Assistant/)).toBeInTheDocument();
    expect(select()).toHaveValue("attic");
  });

  it("shows the server's message when saving fails", async () => {
    overrides["PATCH /rest/v2/rooms/7"] = () => ok({ home_assistant_area_id: ["Home Assistant area \"kitchen\" is linked to another room."] }, 400);
    const user = await renderField();
    await user.selectOptions(select(), "Kitchen");
    await user.click(screen.getByRole("button", { name: "Save area" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Couldn't save the Home Assistant area: home_assistant_area_id: Home Assistant area \"kitchen\" is linked to another room.");
  });

  it("is hidden without a Home Assistant token, and doesn't ask Home Assistant for areas", async () => {
    tokenSet = false;
    start();
    render(<HomeAssistantAreaField roomId={7} />);

    await waitFor(() => expect(useSettingsStore.getState().status).toBe("loaded"));
    await waitFor(() => expect(server.calls("GET", "/rest/v2/rooms/7")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByLabelText("Home Assistant area")).not.toBeInTheDocument());
    expect(server.calls("GET", "/rest/v2/home_assistant/areas")).toHaveLength(0);
  });
});
