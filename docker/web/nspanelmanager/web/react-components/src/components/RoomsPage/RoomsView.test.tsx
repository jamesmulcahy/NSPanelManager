import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSettingsStore } from "../../stores/SettingsStore";
import { fakeServer, ok } from "../HomeAssistantSyncPage/fakeServer";
import RoomsView from "./RoomsView";

// The rooms themselves are not what these tests are about.
vi.mock("../../stores/EntityStore.ts", () => ({ useEntityStatesStore: () => ({ status: "loaded", fetchData: vi.fn() }) }));

let tokenSet: boolean;

beforeEach(() => {
  useSettingsStore.setState({ status: "none", settings: null });
  const server = fakeServer({
    "GET /rest/v2/rooms": () => ok([]),
    "GET /rest/settings": () => ok({ settings: { home_assistant_token_set: tokenSet } }),
  });
  vi.stubGlobal("fetch", server.fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe("RoomsView: Sync from Home Assistant", () => {
  it("links to the sync page when a Home Assistant token is set", async () => {
    tokenSet = true;
    render(<RoomsView />);

    const link = await screen.findByRole("link", { name: "Sync from Home Assistant" });
    expect(link).toHaveAttribute("href", "/home_assistant_sync");
    expect(screen.getByRole("button", { name: "New room" })).toBeInTheDocument();
  });

  it("hides the button without a token", async () => {
    tokenSet = false;
    render(<RoomsView />);

    await waitFor(() => expect(useSettingsStore.getState().status).toBe("loaded"));
    await screen.findByText(/No Rooms found/);
    expect(screen.queryByRole("link", { name: "Sync from Home Assistant" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New room" })).toBeInTheDocument();
  });
});
