import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RoomLink } from "../../api/client";
import { settingsFixture } from "../SettingsPage/testFixtures";
import EntitiesStep from "./EntitiesStep";
import { fakeServer, ok, type Handler } from "./fakeServer";
import { ROWS, roomLink } from "./testFixtures";

let server: ReturnType<typeof fakeServer>;
let overrides: Record<string, Handler>;
let links: RoomLink[];
let excluded: string;
let candidatesReply: (query: URLSearchParams) => ReturnType<Handler>;

function start() {
  server = fakeServer({
    "GET /rest/v2/home_assistant/room_links": () => ok(links),
    "GET /rest/v2/home_assistant/labels": () =>
      ok([
        { label_id: "nspm_ignore", name: "NSPM ignore" },
        { label_id: "acmax", name: "AVPro" },
      ]),
    "GET /rest/v2/settings": () => ok(settingsFixture({ home_assistant_sync_exclude_labels: excluded })),
    "GET /rest/v2/home_assistant/entity_candidates": (request) => candidatesReply(request.query),
    ...overrides,
  });
  vi.stubGlobal("fetch", server.fetchMock);
}

beforeEach(() => {
  document.cookie = "csrftoken=token-123";
  overrides = {};
  excluded = "acmax";
  links = [roomLink({ room_id: 1, name: "Kitchen", link: "linked", area_id: "kitchen" }), roomLink({ room_id: 2, name: "Lounge", link: "linked", area_id: "lounge" })];
  candidatesReply = (query) =>
    ok({
      candidates: query.get("include_imported") === "true" ? ROWS : ROWS.filter((row) => row.already_imported_room_id === null),
      entities_without_area: 32,
      excluded_by_label: 18,
    });
});

afterEach(() => vi.unstubAllGlobals());

async function renderStep(onShowRooms = vi.fn()) {
  start();
  const user = userEvent.setup();
  render(<EntitiesStep onShowRooms={onShowRooms} />);
  await screen.findByLabelText("Select light.k1");
  return user;
}

const box = (entityId: string) => screen.getByLabelText(`Select ${entityId}`) as HTMLInputElement;
const checked = () => screen.getAllByRole("checkbox").filter((input) => (input as HTMLInputElement).checked && /^Select (light|cover|media_player)\./.test(input.getAttribute("aria-label") ?? "")).map((input) => input.getAttribute("aria-label")!.replace("Select ", ""));
const importCalls = () => server.calls("POST", "/rest/v2/home_assistant/import");

describe("the table", () => {
  it("checks nothing by default and shows the columns", async () => {
    await renderStep();

    expect(checked()).toEqual([]);
    expect(screen.getByText("0 selected")).toBeInTheDocument();
    for (const heading of ["Name", "Home Assistant entity", "Type", "Room"]) expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
    expect(screen.getByLabelText("Name for light.k1")).toHaveValue("k1");
    expect(screen.getByRole("button", { name: "Import 0" })).toBeDisabled();
  });

  it("groups rows by room, with the entity id and Home Assistant's name", async () => {
    await renderStep();

    expect(screen.getByRole("columnheader", { name: "Kitchen (3)" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Lounge (2)" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Select light.old")).not.toBeInTheDocument();
  });

  it("shows the entities without an area and the excluded-by-label counts", async () => {
    await renderStep();
    expect(screen.getByText(/32 supported entities have no area in Home Assistant — assign an area there to import them/)).toBeInTheDocument();
    expect(screen.getByText(/18 entities are left out because of an excluded label/)).toBeInTheDocument();
  });
});

describe("selection", () => {
  it("Select all, Select none and Invert selection act on the visible rows only", async () => {
    const user = await renderStep();
    await user.selectOptions(screen.getByLabelText("Filter by type"), "Light");

    await user.click(screen.getByRole("button", { name: "Select all" }));
    expect(checked()).toEqual(["light.k1", "light.k2", "light.l1"]);
    expect(screen.getByText("3 selected")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Filter by type"), "All types");
    await user.click(box("cover.l"));
    await user.selectOptions(screen.getByLabelText("Filter by room"), "Kitchen");
    await user.click(screen.getByRole("button", { name: "Invert selection" }));
    // Kitchen's rows flipped; the Lounge selections are untouched.
    expect(checked()).toEqual(["media_player.k"]);
    expect(screen.getByText(/3 selected \(2 hidden by filters\)/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select none" }));
    expect(screen.getByText(/2 selected \(2 hidden by filters\)/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Filter by room"), "All rooms");
    expect(checked()).toEqual(["light.l1", "cover.l"]);
  });

  it("filters by room and by type", async () => {
    const user = await renderStep();

    await user.selectOptions(screen.getByLabelText("Filter by room"), "Lounge");
    expect(screen.queryByLabelText("Select light.k1")).not.toBeInTheDocument();
    expect(box("cover.l")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Filter by type"), "Cover");
    expect(screen.queryByLabelText("Select light.l1")).not.toBeInTheDocument();
    expect(box("cover.l")).toBeInTheDocument();
  });

  it("has a tri-state group checkbox per room", async () => {
    const user = await renderStep();
    const kitchen = () => screen.getByLabelText("Select all in Kitchen") as HTMLInputElement;

    expect(kitchen().checked).toBe(false);
    await user.click(box("light.k1"));
    expect(kitchen().indeterminate).toBe(true);
    expect(kitchen().checked).toBe(false);

    await user.click(kitchen());
    expect(checked()).toEqual(["light.k1", "light.k2", "media_player.k"]);
    expect(kitchen().indeterminate).toBe(false);
    expect(kitchen().checked).toBe(true);

    await user.click(kitchen());
    expect(checked()).toEqual([]);
  });
});

describe("toggles and already imported rows", () => {
  it("passes the toggles to the server and refetches", async () => {
    const user = await renderStep();
    expect(server.calls("GET", "/rest/v2/home_assistant/entity_candidates")[0].query.toString()).toBe("include_hidden=false&include_imported=false&include_groups=false");

    await user.click(screen.getByLabelText("Show hidden"));
    await user.click(screen.getByLabelText("Show light groups"));
    await user.click(screen.getByLabelText("Show already imported"));

    await waitFor(() => {
      const last = server.calls("GET", "/rest/v2/home_assistant/entity_candidates").at(-1)!;
      expect(last.query.toString()).toBe("include_hidden=true&include_imported=true&include_groups=true");
    });
  });

  it("shows already-imported rows disabled with their current room, and skips them when selecting", async () => {
    const user = await renderStep();
    await user.click(screen.getByLabelText("Show already imported"));
    await screen.findByLabelText("Select light.old");

    expect(box("light.old")).toBeDisabled();
    expect(screen.getByText("Already imported in another room")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select all" }));
    expect(box("light.old").checked).toBe(false);
    expect(screen.getByText("5 selected")).toBeInTheDocument();
  });

  it("keeps the selection across a refetch", async () => {
    const user = await renderStep();
    await user.click(box("light.k1"));
    await user.click(screen.getByLabelText("Show hidden"));
    await waitFor(() => expect(server.calls("GET", "/rest/v2/home_assistant/entity_candidates")).toHaveLength(2));
    await screen.findByLabelText("Select light.k1");
    expect(checked()).toEqual(["light.k1"]);
  });
});

describe("excluded labels", () => {
  it("shows the saved labels, saves a change with a PATCH and refetches the candidates", async () => {
    overrides["PATCH /rest/v2/settings"] = (request) => ok(settingsFixture(request.body as object));
    const user = await renderStep();

    expect(screen.getByLabelText("AVPro")).toBeChecked();
    expect(screen.getByLabelText("NSPM ignore")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save excluded labels" })).toBeDisabled();

    await user.click(screen.getByLabelText("NSPM ignore"));
    await user.click(screen.getByRole("button", { name: "Save excluded labels" }));

    await waitFor(() => expect(server.calls("PATCH", "/rest/v2/settings")).toHaveLength(1));
    expect(server.calls("PATCH", "/rest/v2/settings")[0].body).toEqual({ home_assistant_sync_exclude_labels: "acmax,nspm_ignore" });
    await waitFor(() => expect(server.calls("GET", "/rest/v2/home_assistant/entity_candidates")).toHaveLength(2));
  });

  it("reports a failed save", async () => {
    overrides["PATCH /rest/v2/settings"] = () => ok({ home_assistant_sync_exclude_labels: ["Too long."] }, 400);
    const user = await renderStep();
    await user.click(screen.getByLabelText("NSPM ignore"));
    await user.click(screen.getByRole("button", { name: "Save excluded labels" }));
    expect(await screen.findByText(/Couldn't save the excluded labels: home_assistant_sync_exclude_labels: Too long./)).toBeInTheDocument();
  });
});

describe("importing", () => {
  const created = [
    { entity_id: "light.k1", entity_pk: 1, room_id: 1, page_id: 5, position: 0 },
    { entity_id: "light.k2", entity_pk: 2, room_id: 1, page_id: 5, position: 1 },
    { entity_id: "cover.l", entity_pk: 3, room_id: 2, page_id: 6, position: 0 },
  ];

  it("confirms with a count per room, then posts the selected rows in table order with edited names", async () => {
    overrides["POST /rest/v2/home_assistant/import"] = () => ok({ created, skipped: [], pages_added: 1 }, 201);
    const user = await renderStep();

    await user.click(box("cover.l"));
    await user.click(box("light.k2"));
    await user.click(box("light.k1"));
    await user.clear(screen.getByLabelText("Name for light.k1"));
    await user.type(screen.getByLabelText("Name for light.k1"), "  Island ");
    await user.click(screen.getByRole("button", { name: "Import 3" }));

    const dialog = screen.getByRole("dialog", { name: "Confirm import" });
    expect(within(dialog).getByText("Kitchen: 2")).toBeInTheDocument();
    expect(within(dialog).getByText("Lounge: 1")).toBeInTheDocument();
    expect(importCalls()).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Confirm import" }));

    await waitFor(() => expect(importCalls()).toHaveLength(1));
    expect(importCalls()[0].body).toEqual({
      items: [
        { entity_id: "light.k1", room_id: 1, entity_type: "light", friendly_name: "Island" },
        { entity_id: "light.k2", room_id: 1, entity_type: "light", friendly_name: "k2" },
        { entity_id: "cover.l", room_id: 2, entity_type: "cover", friendly_name: "l" },
      ],
    });

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("Imported 3 entities, adding 1 page.");
    expect(result).toHaveTextContent("Kitchen: 2 created");
    expect(result).toHaveTextContent("Lounge: 1 created");
    expect(checked()).toEqual([]);
    await waitFor(() => expect(server.calls("GET", "/rest/v2/home_assistant/entity_candidates")).toHaveLength(2));
  });

  it("lists skipped entities with the reason", async () => {
    overrides["POST /rest/v2/home_assistant/import"] = () => ok({ created: created.slice(0, 1), skipped: [{ entity_id: "light.k2", reason: "already_imported" }], pages_added: 0 }, 201);
    const user = await renderStep();
    await user.click(box("light.k1"));
    await user.click(screen.getByRole("button", { name: "Import 1" }));
    await user.click(screen.getByRole("button", { name: "Confirm import" }));

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("Imported 1 entity.");
    expect(result).toHaveTextContent("Skipped:");
    expect(result).toHaveTextContent("light.k2: already imported");
    expect(result).not.toHaveTextContent("adding");
  });

  it("cancel closes the confirmation without importing", async () => {
    const user = await renderStep();
    await user.click(box("light.k1"));
    await user.click(screen.getByRole("button", { name: "Import 1" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(importCalls()).toHaveLength(0);
    expect(box("light.k1").checked).toBe(true);
  });

  it("Escape closes the confirmation without importing", async () => {
    const user = await renderStep();
    await user.click(box("light.k1"));
    await user.click(screen.getByRole("button", { name: "Import 1" }));
    expect(screen.getByRole("dialog", { name: "Confirm import" })).toHaveAttribute("aria-modal", "true");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(importCalls()).toHaveLength(0);
  });

  it("scrolls the import result into view", async () => {
    overrides["POST /rest/v2/home_assistant/import"] = () => ok({ created: created.slice(0, 1), skipped: [], pages_added: 0 }, 201);
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    try {
      const user = await renderStep();
      await user.click(box("light.k1"));
      await user.click(screen.getByRole("button", { name: "Import 1" }));
      expect(scrollIntoView).not.toHaveBeenCalled();
      await user.click(screen.getByRole("button", { name: "Confirm import" }));
      await screen.findByRole("status");
      expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    } finally {
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    }
  });

  it("blocks the import while a selected row has an empty name", async () => {
    const user = await renderStep();
    await user.click(box("light.k1"));
    await user.clear(screen.getByLabelText("Name for light.k1"));
    expect(screen.getByText("Enter a name.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import 1" })).toBeDisabled();
  });

  it("shows a failed import as an error and keeps the selection", async () => {
    overrides["POST /rest/v2/home_assistant/import"] = () => ok({ detail: "Home Assistant is unreachable" }, 502);
    const user = await renderStep();
    await user.click(box("light.k1"));
    await user.click(screen.getByRole("button", { name: "Import 1" }));
    await user.click(screen.getByRole("button", { name: "Confirm import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Import failed: Home Assistant is unreachable");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(box("light.k1").checked).toBe(true);
  });
});

describe("failures and empty states", () => {
  it("shows a 502 from the candidates as a banner, not as an empty list", async () => {
    candidatesReply = () => ok({ detail: "Home Assistant answered HTTP 401" }, 502);
    start();
    render(<EntitiesStep onShowRooms={() => {}} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load entities: Home Assistant answered HTTP 401");
    expect(screen.queryByText("Nothing to import.")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("links back to step 1 when no room is linked", async () => {
    links = [roomLink({ room_id: 1, name: "Kitchen" }), roomLink({ room_id: 2, name: "Porch", link: "none" })];
    const onShowRooms = vi.fn();
    start();
    const user = userEvent.setup();
    render(<EntitiesStep onShowRooms={onShowRooms} />);

    expect(await screen.findByText(/No rooms are linked/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Link rooms in step 1" }));
    expect(onShowRooms).toHaveBeenCalled();
  });

  it("says so when nothing is left to import", async () => {
    candidatesReply = () => ok({ candidates: [], entities_without_area: 0, excluded_by_label: 0 });
    start();
    render(<EntitiesStep onShowRooms={() => {}} />);
    expect(await screen.findByText("Nothing to import.")).toBeInTheDocument();
  });
});
