import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Settings } from "../../api/client";
import { Notify } from "../NSPanelToastContainer";
import SettingsPage from "./SettingsPage";
import { settingsFixture } from "./testFixtures";

vi.mock("../NSPanelToastContainer", () => ({ Notify: vi.fn() }));

type Reply = { status: number; body: unknown };

// A fake server: GET returns `stored`; PATCH merges the body into it (or returns `patchReply`).
let stored: Settings;
let patchReply: Reply | null;
let getReply: Reply | null;
// The reply to GET /rest/home_assistant/entities; null makes the request fail.
let entitiesReply: Reply | null;
const CALENDARS_REPLY: Reply = {
  status: 200,
  body: {
    items: [
      { type: "home_assistant", label: "Family Calendar", item_id: "calendar.family", item: {} },
      { type: "home_assistant", label: "School Calendar", item_id: "calendar.school", item: {} },
      { type: "home_assistant", label: "Waste Collection", item_id: "calendar.waste", item: {} },
    ],
    errors: [],
  },
};
const requests: { method: string; url: string; headers: Headers; body: unknown }[] = [];

function json(reply: Reply) {
  return new Response(JSON.stringify(reply.body), { status: reply.status, headers: { "Content-Type": "application/json" } });
}

const fetchMock = vi.fn(async (input: Request | string, init?: RequestInit) => {
  const request = typeof input === "string" ? new Request(new URL(input, "http://localhost"), init) : input;
  const text = await request.clone().text();
  const url = new URL(request.url);
  requests.push({ method: request.method, url: url.pathname + url.search, headers: request.headers, body: text ? JSON.parse(text) : undefined });
  if (url.pathname === "/rest/v2/settings" && request.method === "GET") {
    return json(getReply ?? { status: 200, body: stored });
  }
  if (url.pathname === "/rest/v2/settings" && request.method === "PATCH") {
    if (patchReply) {
      return json(patchReply);
    }
    const body = JSON.parse(text);
    stored = { ...stored, ...body };
    for (const secret of ["mqtt_password", "home_assistant_token", "openhab_token"]) {
      if (secret in body) {
        delete (stored as Record<string, unknown>)[secret];
        (stored as Record<string, unknown>)[`${secret}_set`] = body[secret] !== "";
      }
    }
    return json({ status: 200, body: stored });
  }
  if (url.pathname === "/rest/home_assistant/entities") {
    if (!entitiesReply) {
      throw new TypeError("Failed to fetch");
    }
    return json(entitiesReply);
  }
  if (url.pathname === "/rest/get_ip_by_hostname") {
    return json({ status: 200, body: { ip: "10.0.0.5" } });
  }
  if (url.pathname.endsWith("/test")) {
    return json({ status: 200, body: { status: "success" } });
  }
  throw new Error(`Unexpected request: ${request.method} ${url.pathname}`);
});

const patches = () => requests.filter((request) => request.method === "PATCH");
const saveButton = () => screen.getByRole("button", { name: "Save" });

async function renderPage(settings: Partial<Settings> = {}) {
  stored = settingsFixture(settings);
  const user = userEvent.setup();
  render(<SettingsPage logDownloadUrl="/ingress/download_mqttmanager_log" />);
  await screen.findByLabelText("MQTT port");
  return user;
}

async function save(user: ReturnType<typeof userEvent.setup>) {
  await user.click(saveButton());
  await waitFor(() => expect(saveButton()).toBeDisabled());
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "csrftoken=token-123";
  requests.length = 0;
  patchReply = null;
  getReply = null;
  entitiesReply = CALENDARS_REPLY;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(Notify).mockClear();
});

describe("loading", () => {
  it("shows the stored settings", async () => {
    await renderPage();

    expect(screen.getByLabelText("MQTT port")).toHaveValue(1883);
    expect(screen.getByLabelText("MQTT server")).toHaveValue("mqtt.local");
    expect(screen.getByLabelText("Screensaver mode")).toHaveValue("with_background");
    expect(within(screen.getByRole("group", { name: "Entity update mode" })).getByLabelText("Optimistic")).toBeChecked();
    expect(within(screen.getByRole("group", { name: "Color temperature slider" })).getByLabelText("Keep default")).toBeChecked();
    expect(screen.getByRole("link", { name: /Download/ })).toHaveAttribute("href", "/ingress/download_mqttmanager_log");
    expect(saveButton()).toBeDisabled();
  });

  it("shows a load error and retries", async () => {
    stored = settingsFixture();
    getReply = { status: 500, body: {} };
    const user = userEvent.setup();
    render(<SettingsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load the settings: HTTP 500");

    getReply = null;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByLabelText("MQTT port")).toHaveValue(1883);
  });

  it("marks settings with no valid stored value, and doesn't send them unless filled in", async () => {
    const user = await renderPage({ mqtt_port: null, screensaver_mode: null });

    expect(screen.getByLabelText("MQTT port")).toHaveValue(null);
    expect(screen.getAllByText("No valid value is stored. Enter one.").length).toBe(2);

    await user.clear(screen.getByLabelText("MQTT server"));
    await user.type(screen.getByLabelText("MQTT server"), "broker");
    await save(user);

    expect(patches()[0].body).toEqual({ mqtt_server: "broker" });
  });
});

describe("firmware source", () => {
  it("shows the stored repository and release", async () => {
    await renderPage();

    expect(screen.getByLabelText("GitHub repository")).toHaveValue("jamesmulcahy/NSPanelManager-firmware");
    expect(screen.getByLabelText("Release")).toHaveValue("latest");
  });

  it("saves a changed repository and release", async () => {
    const user = await renderPage();

    await user.clear(screen.getByLabelText("GitHub repository"));
    await user.type(screen.getByLabelText("GitHub repository"), "a/b");
    await user.clear(screen.getByLabelText("Release"));
    await user.type(screen.getByLabelText("Release"), "build-1");
    await save(user);

    expect(patches()[0].body).toEqual({ firmware_github_repo: "a/b", firmware_github_release: "build-1" });
  });

  it("rejects a malformed repository or release and saves nothing", async () => {
    const user = await renderPage();

    await user.clear(screen.getByLabelText("GitHub repository"));
    await user.type(screen.getByLabelText("GitHub repository"), "not a repo");
    await user.clear(screen.getByLabelText("Release"));
    await user.click(saveButton());

    expect(await screen.findByText(/Use the form owner\/repository/)).toBeInTheDocument();
    expect(screen.getByText(/Use "latest" or a release tag/)).toBeInTheDocument();
    expect(patches()).toHaveLength(0);
  });

  it("resets each field to its default", async () => {
    const user = await renderPage({ firmware_github_repo: "someone/other", firmware_github_release: "build-1234abcd" });

    await user.click(screen.getByRole("button", { name: "Reset repository" }));
    await user.click(screen.getByRole("button", { name: "Reset release" }));

    expect(screen.getByLabelText("GitHub repository")).toHaveValue("jamesmulcahy/NSPanelManager-firmware");
    expect(screen.getByLabelText("Release")).toHaveValue("latest");
    await save(user);
    expect(patches()[0].body).toEqual({ firmware_github_repo: "jamesmulcahy/NSPanelManager-firmware", firmware_github_release: "latest" });
  });
});

describe("saving", () => {
  it("sends only the changed settings, with the CSRF token", async () => {
    const user = await renderPage();

    await user.clear(screen.getByLabelText("MQTT port"));
    await user.type(screen.getByLabelText("MQTT port"), "1884");
    await user.selectOptions(screen.getByLabelText("Screensaver mode"), "no_screensaver");
    await user.click(within(screen.getByRole("group", { name: "Color temperature slider" })).getByLabelText("Reverse"));
    await save(user);

    expect(patches()).toHaveLength(1);
    expect(patches()[0].body).toEqual({ mqtt_port: 1884, screensaver_mode: "no_screensaver", reverse_color_temp: true });
    expect(patches()[0].headers.get("X-CSRFToken")).toBe("token-123");
    expect(Notify).toHaveBeenCalledWith(expect.objectContaining({ level: "success" }));
  });

  it("is clean again after saving", async () => {
    const user = await renderPage();

    await user.clear(screen.getByLabelText("MQTT port"));
    await user.type(screen.getByLabelText("MQTT port"), "1884");
    await save(user);

    expect(screen.getByLabelText("MQTT port")).toHaveValue(1884);
    expect(saveButton()).toBeDisabled();
  });

  it("sends nothing for a change that was undone", async () => {
    const user = await renderPage();

    await user.clear(screen.getByLabelText("MQTT port"));
    await user.type(screen.getByLabelText("MQTT port"), "1883");

    expect(saveButton()).toBeDisabled();
  });

  it("discards changes", async () => {
    const user = await renderPage();

    await user.clear(screen.getByLabelText("MQTT server"));
    await user.type(screen.getByLabelText("MQTT server"), "other");
    await user.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(screen.getByLabelText("MQTT server")).toHaveValue("mqtt.local");
    expect(saveButton()).toBeDisabled();
  });

  it("sends a blank number as null so the server reports it", async () => {
    const user = await renderPage();

    await user.clear(screen.getByLabelText("MQTT port"));
    await save(user);

    expect(patches()[0].body).toEqual({ mqtt_port: null });
  });

  it("shows field errors next to their fields and saves nothing", async () => {
    const user = await renderPage();
    patchReply = { status: 400, body: { screen_dim_level: ["Ensure this value is greater than or equal to 1."], theme: ["Unknown setting."] } };

    await user.clear(screen.getByLabelText("Screen brightness (%)"));
    await user.type(screen.getByLabelText("Screen brightness (%)"), "0");
    await user.click(saveButton());

    expect(await screen.findByText("Ensure this value is greater than or equal to 1.")).toBeInTheDocument();
    expect(screen.getByLabelText("Screen brightness (%)")).toHaveAttribute("aria-invalid", "true");
    expect(Notify).toHaveBeenCalledWith(expect.objectContaining({ level: "error", message: "Nothing was saved. theme: Unknown setting." }));
  });

  it("reports other errors", async () => {
    const user = await renderPage();
    patchReply = { status: 403, body: { detail: "CSRF Failed: CSRF token missing." } };

    await user.clear(screen.getByLabelText("MQTT port"));
    await user.type(screen.getByLabelText("MQTT port"), "1884");
    await user.click(saveButton());

    await waitFor(() => expect(Notify).toHaveBeenCalledWith(expect.objectContaining({ level: "error", message: "Couldn't save the settings: CSRF Failed: CSRF token missing." })));
  });
});

describe("secrets", () => {
  it("keeps a stored secret when left blank", async () => {
    const user = await renderPage();

    await user.type(screen.getByLabelText("MQTT username"), "x");
    await save(user);

    expect(patches()[0].body).toEqual({ mqtt_username: "nspmx" });
  });

  it("sends a new secret", async () => {
    const user = await renderPage();

    await user.type(screen.getByLabelText("MQTT password"), "hunter2");
    await save(user);

    expect(patches()[0].body).toEqual({ mqtt_password: "hunter2" });
    expect(screen.getByLabelText("MQTT password")).toHaveValue("");
  });

  it("clears a stored secret", async () => {
    const user = await renderPage();

    await user.click(screen.getByLabelText("Clear the stored mqtt password"));
    expect(screen.getByLabelText("MQTT password")).toBeDisabled();
    await save(user);

    expect(patches()[0].body).toEqual({ mqtt_password: "" });
    expect(screen.queryByLabelText("Clear the stored mqtt password")).not.toBeInTheDocument();
  });

  it("offers clear only for a stored secret", async () => {
    await renderPage();

    expect(screen.getByLabelText("Clear the stored mqtt password")).toBeInTheDocument();
    expect(screen.queryByLabelText("Clear the stored openhab token")).not.toBeInTheDocument();
  });
});

describe("Home Assistant add-on", () => {
  it("locks the Home Assistant settings", async () => {
    await renderPage({ is_home_assistant_addon: true });

    expect(screen.getByText(/managed by Home Assistant and are locked/)).toBeInTheDocument();
    expect(screen.getByLabelText("Home Assistant address")).toBeDisabled();
    expect(screen.getByLabelText("Home Assistant token")).toBeDisabled();
    expect(screen.queryByLabelText("Clear the stored home assistant token")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test Home Assistant" })).not.toBeInTheDocument();
  });
});

describe("conditional settings", () => {
  it("shows the outside temperature setting only for the screensaver modes without weather", async () => {
    const user = await renderPage();
    const outside = () => screen.queryByRole("group", { name: "Screensaver outside temperature" });

    expect(outside()).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Screensaver mode"), "datetime_with_background");
    expect(outside()).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Screensaver mode"), "datetime_without_background");
    expect(outside()).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Screensaver mode"), "no_screensaver");
    expect(outside()).not.toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("loads the manager address and port from the page URL", async () => {
    const user = await renderPage();

    const [addressButton, portButton] = screen.getAllByRole("button", { name: "Load from URL" });
    await user.click(addressButton);
    await waitFor(() => expect(screen.getByLabelText("Manager address")).toHaveValue("10.0.0.5"));
    await user.click(portButton);
    expect(screen.getByLabelText("Manager port")).toHaveValue(Number(window.location.port || 80));

    const lookup = requests.find((request) => request.url === "/rest/get_ip_by_hostname");
    expect(lookup?.body).toEqual({ hostname: window.location.hostname });
    expect(lookup?.headers.get("X-CSRFToken")).toBe("token-123");
    expect(saveButton()).toBeEnabled();
  });

  it("tests the manager address with the values in the form", async () => {
    const user = await renderPage();

    await user.click(screen.getByRole("button", { name: "Test manager address" }));

    await waitFor(() => expect(Notify).toHaveBeenCalledWith(expect.objectContaining({ level: "success" })));
    expect(requests.some((request) => request.url === "/rest/mqttmanager/test?address=192.168.1.10&port=8000")).toBe(true);
  });

  it("tests Home Assistant only with a typed token", async () => {
    const user = await renderPage();
    const test = () => screen.getByRole("button", { name: "Test Home Assistant" });

    expect(test()).toBeDisabled();
    await user.type(screen.getByLabelText("Home Assistant token"), "abc");
    await user.click(test());

    await waitFor(() => expect(requests.some((request) => request.url === "/rest/home_assistant/test?address=http%3A%2F%2Fha.local%3A8123&token=abc")).toBe(true));
  });
});

// Records what the preview schedules. Oscillators end only when a test calls end().
class FakeParam {
  value = 0;
  readonly events: [string, number, number][] = [];
  setValueAtTime(value: number, time: number) {
    this.events.push(["set", value, time]);
  }
  linearRampToValueAtTime(value: number, time: number) {
    this.events.push(["ramp", value, time]);
  }
}

class FakeNode {
  connect<T>(target: T) {
    return target;
  }
  disconnect() {}
}

class FakeOscillator extends FakeNode {
  type = "sine";
  frequency = new FakeParam();
  onended: (() => void) | null = null;
  stopped = false;
  start() {}
  stop(time?: number) {
    if (time === undefined) {
      this.stopped = true;
      this.onended?.();
    }
  }
  end() {
    this.onended?.();
  }
}

const oscillators: FakeOscillator[] = [];
const filters: { type: string }[] = [];

class FakeAudioContext {
  state = "running";
  currentTime = 0;
  destination = new FakeNode();
  createOscillator() {
    const oscillator = new FakeOscillator();
    oscillators.push(oscillator);
    return oscillator;
  }
  createGain() {
    return Object.assign(new FakeNode(), { gain: new FakeParam() });
  }
  createBiquadFilter() {
    const filter = Object.assign(new FakeNode(), { type: "", frequency: new FakeParam(), Q: new FakeParam() });
    filters.push(filter);
    return filter;
  }
  resume() {
    return Promise.resolve();
  }
}

// The frequencies a preview played, in order.
const played = (oscillator: FakeOscillator) => oscillator.frequency.events.map(([, frequency]) => frequency);

describe("buzzer sounds", () => {
  const choice = (label: string) => screen.getByLabelText(label) as HTMLSelectElement;
  const rtttl = (label: string) => screen.getByLabelText(`${label} RTTTL`) as HTMLInputElement;
  const previewButton = (label: string) => screen.getByRole("button", { name: new RegExp(`(Preview|Stop) the ${label.toLowerCase()}`) });

  beforeEach(() => {
    vi.stubGlobal("AudioContext", FakeAudioContext);
    oscillators.length = 0;
    filters.length = 0;
  });

  it("is off by default, except for the timer", async () => {
    await renderPage();

    expect(choice("Timer finished")).toHaveDisplayValue("Alarm");
    expect(rtttl("Timer finished")).toHaveValue("timer:d=8,o=6,b=200:c7,p,c7,p,c7,p,c7");
    expect(screen.getByText(/repeated every few seconds until it is dismissed. Plays for 1.05 s./)).toBeInTheDocument();

    expect(choice("Screen touch")).toHaveDisplayValue("Off");
    expect(choice("Scene activated")).toHaveDisplayValue("Same as screen touch");
    expect(choice("Scene saved")).toHaveDisplayValue("Off");
    for (const label of ["Screen touch", "Scene activated", "Scene saved"]) {
      expect(rtttl(label)).toHaveValue("");
      expect(previewButton(label)).toBeDisabled();
    }
  });

  it("shows stored sounds as their preset, or as custom", async () => {
    await renderPage({ buzzer_sound_touch: "chime:d=32,o=6,b=190:g6,16p,32c7", buzzer_sound_scene_activated: "silent:d=64,o=6,b=900:p", buzzer_sound_scene_saved: "mine:d=8:c,d" });

    expect(choice("Screen touch")).toHaveDisplayValue("Chime");
    expect(choice("Scene activated")).toHaveDisplayValue("Silent");
    expect(choice("Scene saved")).toHaveDisplayValue("Custom…");
    expect(rtttl("Scene saved")).toHaveValue("mine:d=8:c,d");
    expect(screen.getByText(/Played on every press of the screen. Plays for 157 ms./)).toBeInTheDocument();
    expect(screen.getByText(/instead of the touch sound .* Silent\./)).toBeInTheDocument();
  });

  it("saves a chosen preset as its RTTTL, and nothing else", async () => {
    const user = await renderPage();

    await user.selectOptions(choice("Screen touch"), "Tick");
    expect(rtttl("Screen touch")).toHaveValue("tick:d=64,o=7,b=625:b");
    await save(user);

    expect(patches()).toHaveLength(1);
    expect(patches()[0].body).toEqual({ buzzer_sound_touch: "tick:d=64,o=7,b=625:b" });
  });

  it("turns a sound off by saving it blank", async () => {
    const user = await renderPage({ buzzer_sound_scene_saved: "saved:d=16,o=6,b=200:c,e,g,8c7" });

    await user.selectOptions(choice("Scene saved"), "Off");
    await save(user);

    expect(patches()[0].body).toEqual({ buzzer_sound_scene_saved: "" });
  });

  it("turns the timer sound off by saving it blank", async () => {
    const user = await renderPage();

    await user.selectOptions(choice("Timer finished"), "Off");
    expect(rtttl("Timer finished")).toHaveValue("");
    await save(user);

    expect(patches()).toHaveLength(1);
    expect(patches()[0].body).toEqual({ buzzer_sound_timer_fired: "" });
  });

  it("round-trips a timer preset and offers the Alarm first", async () => {
    const user = await renderPage({ buzzer_sound_timer_fired: "" });

    const options = Array.from(choice("Timer finished").options).map((option) => option.text);
    expect(options.slice(0, 3)).toEqual(["Off", "Alarm", "Rising"]);
    await user.selectOptions(choice("Timer finished"), "Alarm");
    await save(user);

    expect(patches()[0].body).toEqual({ buzzer_sound_timer_fired: "timer:d=8,o=6,b=200:c7,p,c7,p,c7,p,c7" });
  });

  it("lets a preset be edited as a custom sound", async () => {
    const user = await renderPage({ buzzer_sound_touch: "tick:d=64,o=7,b=625:b" });

    await user.selectOptions(choice("Screen touch"), "Custom…");
    expect(choice("Screen touch")).toHaveDisplayValue("Custom…");
    expect(rtttl("Screen touch")).toHaveFocus();
    await user.type(rtttl("Screen touch"), ",b");
    await save(user);

    expect(patches()[0].body).toEqual({ buzzer_sound_touch: "tick:d=64,o=7,b=625:b,b" });
  });

  it("shows invalid RTTTL as it is typed and doesn't save it", async () => {
    const user = await renderPage();

    await user.selectOptions(choice("Scene saved"), "Custom…");
    await user.type(rtttl("Scene saved"), "x:b=999:c");

    expect(screen.getByText("b must be 1 to 900.")).toBeInTheDocument();
    expect(rtttl("Scene saved")).toHaveAttribute("aria-invalid", "true");
    expect(previewButton("Scene saved")).toBeDisabled();
    await user.click(saveButton());
    expect(patches()).toHaveLength(0);

    await user.clear(rtttl("Scene saved"));
    await user.type(rtttl("Scene saved"), "x:b=900:c");
    expect(screen.queryByText("b must be 1 to 900.")).not.toBeInTheDocument();
    await save(user);
    expect(patches()[0].body).toEqual({ buzzer_sound_scene_saved: "x:b=900:c" });
  });

  it("flags a stored sound the panel can't play", async () => {
    await renderPage({ buzzer_sound_touch: "beep" });

    expect(choice("Screen touch")).toHaveDisplayValue("Custom…");
    expect(screen.getByText(/Expected name:defaults:notes/)).toBeInTheDocument();
  });

  it("shows a server error next to the sound", async () => {
    const user = await renderPage();
    patchReply = { status: 400, body: { buzzer_sound_touch: ["Rejected by the server."] } };

    await user.selectOptions(choice("Screen touch"), "Chime");
    await user.click(saveButton());

    expect(await screen.findByText("Rejected by the server.")).toBeInTheDocument();
  });

  it("previews the panel's steps, one sound at a time", async () => {
    const user = await renderPage({ buzzer_sound_touch: "chime:d=32,o=6,b=190:g6,16p,32c7", buzzer_sound_scene_saved: "confirm:d=16,o=6,b=357:e,g" });

    await user.click(previewButton("Screen touch"));
    expect(oscillators).toHaveLength(1);
    expect(oscillators[0].type).toBe("square");
    expect(played(oscillators[0])).toEqual([1568, 2093]);
    expect(previewButton("Screen touch")).toHaveAccessibleName("Stop the screen touch preview");

    // Starting another preview stops the first
    await user.click(previewButton("Scene saved"));
    expect(oscillators[0].stopped).toBe(true);
    expect(played(oscillators[1])).toEqual([1319, 1568]);
    expect(previewButton("Screen touch")).toHaveAccessibleName("Preview the screen touch sound");

    // And it ends by itself
    oscillators[1].end();
    await waitFor(() => expect(previewButton("Scene saved")).toHaveAccessibleName("Preview the scene saved sound"));
    expect(patches()).toHaveLength(0);
  });

  it("previews the touch sound for a blank scene activated sound", async () => {
    const user = await renderPage({ buzzer_sound_touch: "tick:d=64,o=7,b=625:b" });

    await user.click(previewButton("Scene activated"));
    expect(played(oscillators[0])).toEqual([3951]);
  });

  it("simulates the piezo unless that is turned off", async () => {
    const user = await renderPage({ buzzer_sound_touch: "tick:d=64,o=7,b=625:b" });

    await user.click(previewButton("Screen touch"));
    expect(filters).toEqual([expect.objectContaining({ type: "bandpass" })]);

    await user.click(screen.getByLabelText(/sound like the panel's buzzer/));
    await user.click(previewButton("Screen touch")); // stop
    await user.click(previewButton("Screen touch"));
    expect(oscillators).toHaveLength(2);
    expect(filters).toHaveLength(1);
  });

  it("says when the browser can't preview", async () => {
    vi.stubGlobal("AudioContext", undefined);
    await renderPage({ buzzer_sound_touch: "tick:d=64,o=7,b=625:b" });

    expect(screen.getByText("This browser can't play the preview.")).toBeInTheDocument();
    expect(previewButton("Screen touch")).toBeDisabled();
  });
});

describe("screensaver cards", () => {
  const checkbox = () => screen.getByRole("checkbox", { name: "Show calendar card" });
  const seconds = () => screen.getByLabelText("Calendar card seconds");

  it("shows the cards that are stored", async () => {
    await renderPage({ screensaver_cards: "calendar:15", screensaver_base_card_seconds: 8 });

    expect(screen.getByLabelText("Weather card seconds")).toHaveValue(8);
    expect(checkbox()).toBeChecked();
    expect(seconds()).toHaveValue(15);
  });

  it("has the calendar card off, and its time disabled, when none is stored", async () => {
    await renderPage();

    expect(checkbox()).not.toBeChecked();
    expect(seconds()).toBeDisabled();
  });

  it("turns the calendar card on with 10 seconds", async () => {
    const user = await renderPage();

    await user.click(checkbox());
    await save(user);

    expect(patches()[0].body).toEqual({ screensaver_cards: "calendar:10" });
  });

  it("turns the now playing card on with 10 seconds, after the cards already there", async () => {
    const user = await renderPage({ screensaver_cards: "calendar:15" });

    await user.click(screen.getByRole("checkbox", { name: "Show now playing card" }));
    await save(user);

    expect(patches()[0].body).toEqual({ screensaver_cards: "calendar:15,now_playing:10" });
  });

  it("changes the time, and keeps card types it has no row for", async () => {
    const user = await renderPage({ screensaver_cards: "news:7,calendar:15" });

    await user.clear(seconds());
    await user.type(seconds(), "30");
    await save(user);

    expect(patches()[0].body).toEqual({ screensaver_cards: "news:7,calendar:30" });
  });

  it("turns the calendar card off", async () => {
    const user = await renderPage({ screensaver_cards: "calendar:15" });

    await user.click(checkbox());
    await save(user);

    expect(patches()[0].body).toEqual({ screensaver_cards: "" });
  });

  it("brings a time outside 3 to 300 back into range", async () => {
    const user = await renderPage({ screensaver_cards: "calendar:15" });

    await user.clear(seconds());
    await user.type(seconds(), "1000");
    await user.tab();

    expect(seconds()).toHaveValue(300);
    await save(user);
    expect(patches()[0].body).toEqual({ screensaver_cards: "calendar:300" });
  });

  it("saves the weather card seconds", async () => {
    const user = await renderPage();

    await user.clear(screen.getByLabelText("Weather card seconds"));
    await user.type(screen.getByLabelText("Weather card seconds"), "20");
    await save(user);

    expect(patches()[0].body).toEqual({ screensaver_base_card_seconds: 20 });
  });
});

describe("calendar section", () => {
  const picker = () => screen.getByLabelText("Calendar entities");

  it("edits the calendar limits", async () => {
    const user = await renderPage({ calendar_entity_ids: "calendar.family" });

    expect(screen.getByLabelText("Most events shown")).toHaveValue(5);
    expect(screen.getByLabelText("Look ahead (hours)")).toHaveValue(48);
    expect(screen.getByLabelText("Refresh every (minutes)")).toHaveValue(5);

    await user.clear(screen.getByLabelText("Most events shown"));
    await user.type(screen.getByLabelText("Most events shown"), "8");
    await save(user);

    expect(patches()[0].body).toEqual({ calendar_max_events: 8 });
  });

  it("asks Home Assistant for its calendars only", async () => {
    await renderPage({ calendar_entity_ids: "calendar.family" });

    await screen.findByText("Family Calendar");
    const request = requests.find((entry) => entry.url.startsWith("/rest/home_assistant/entities"));
    expect(request).toBeDefined();
    expect(JSON.parse(new URL(request!.url, "http://localhost").searchParams.get("filter")!)).toEqual({ type: ["calendar"] });
  });

  it("shows the saved calendars by their friendly names and leaves the setting alone when nothing changes", async () => {
    await renderPage({ calendar_entity_ids: "calendar.family, calendar.school" });

    expect(await screen.findByText("Family Calendar")).toBeInTheDocument();
    expect(screen.getByText("School Calendar")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Choose calendars" })).toBeChecked();
    expect(saveButton()).toBeDisabled();
  });

  it("chooses a calendar from the list and keeps the others", async () => {
    const user = await renderPage({ calendar_entity_ids: "calendar.family" });
    await screen.findByText("Family Calendar");

    await user.type(picker(), "school{Enter}");
    await save(user);

    expect(patches()[0].body).toEqual({ calendar_entity_ids: "calendar.family,calendar.school" });
  });

  it("removes a calendar", async () => {
    const user = await renderPage({ calendar_entity_ids: "calendar.family,calendar.school" });
    await screen.findByText("Family Calendar");

    await user.click(screen.getByLabelText("Remove Family Calendar"));
    await save(user);

    expect(patches()[0].body).toEqual({ calendar_entity_ids: "calendar.school" });
  });

  it("starts on Choose, with nothing chosen, when the calendar has not been set up", async () => {
    await renderPage({ calendar_entity_ids: "" });

    expect(screen.getByRole("radio", { name: "Choose calendars" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "All calendars" })).not.toBeChecked();
    expect(screen.getByText(/With none, the calendar stays off/)).toBeInTheDocument();
  });

  it("round-trips all", async () => {
    const user = await renderPage({ calendar_entity_ids: "all" });

    expect(screen.getByRole("radio", { name: "All calendars" })).toBeChecked();
    expect(screen.queryByLabelText("Calendar entities")).not.toBeInTheDocument();
    expect(saveButton()).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "Choose calendars" }));
    await save(user);

    expect(patches()[0].body).toEqual({ calendar_entity_ids: "" });
  });

  it("saves all when All calendars is picked, and brings the choice back when Choose is picked again", async () => {
    const user = await renderPage({ calendar_entity_ids: "calendar.family,calendar.school" });
    await screen.findByText("Family Calendar");

    await user.click(screen.getByRole("radio", { name: "All calendars" }));
    expect(screen.queryByLabelText("Calendar entities")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Choose calendars" }));
    expect(await screen.findByText("School Calendar")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "All calendars" }));
    await save(user);

    expect(patches()[0].body).toEqual({ calendar_entity_ids: "all" });
  });

  it("keeps saved calendars that Home Assistant no longer has, and shows them as missing", async () => {
    const user = await renderPage({ calendar_entity_ids: "calendar.family,calendar.gone" });

    expect(await screen.findByText("calendar.gone (missing)")).toBeInTheDocument();
    expect(screen.getByText(/Not in Home Assistant any more: calendar\.gone/)).toBeInTheDocument();

    // Adding another one keeps it.
    await user.type(picker(), "school{Enter}");
    await save(user);
    expect(patches()[0].body).toEqual({ calendar_entity_ids: "calendar.family,calendar.gone,calendar.school" });
  });

  it("lets a missing calendar be removed", async () => {
    const user = await renderPage({ calendar_entity_ids: "calendar.family,calendar.gone" });
    await screen.findByText("calendar.gone (missing)");

    await user.click(screen.getByLabelText("Remove calendar.gone"));
    await save(user);

    expect(patches()[0].body).toEqual({ calendar_entity_ids: "calendar.family" });
    expect(screen.queryByText(/Not in Home Assistant any more/)).not.toBeInTheDocument();
  });

  it("falls back to the text field when the calendars can't be fetched", async () => {
    entitiesReply = null;
    const user = await renderPage({ calendar_entity_ids: "calendar.family" });

    const field = await screen.findByLabelText("Calendars");
    expect(field).toHaveValue("calendar.family");
    expect(screen.getByText(/Couldn't load the calendars from Home Assistant/)).toBeInTheDocument();

    await user.clear(field);
    await user.type(field, "calendar.family, calendar.school");
    await save(user);

    expect(patches()[0].body).toEqual({ calendar_entity_ids: "calendar.family, calendar.school" });
  });

  it.each([
    ["an HTTP error", { status: 500, body: {} }],
    ["Home Assistant not being reachable", { status: 200, body: { items: [], errors: ["Home Assistant address and/or access token not configured"] } }],
  ])("falls back to the text field on %s", async (_name, reply) => {
    entitiesReply = reply;
    await renderPage({ calendar_entity_ids: "all" });

    expect(await screen.findByLabelText("Calendars")).toHaveValue("all");
  });

  it("is replaced by a hint when Home Assistant is not configured", async () => {
    await renderPage({ home_assistant_address: "", home_assistant_token_set: false });

    expect(screen.queryByLabelText("Calendar entities")).not.toBeInTheDocument();
    expect(screen.getByText(/Calendars come from Home Assistant/)).toBeInTheDocument();
  });

  it("is hidden when Home Assistant has an address but no token", async () => {
    await renderPage({ home_assistant_token_set: false });

    expect(screen.queryByLabelText("Calendar entities")).not.toBeInTheDocument();
    expect(requests.some((entry) => entry.url.startsWith("/rest/home_assistant/entities"))).toBe(false);
  });
});

describe("energy section", () => {
  it("reads the power and price from Home Assistant's Energy settings by default", async () => {
    await renderPage();

    expect(screen.getByLabelText("Power from")).toHaveValue("home_assistant_energy");
    expect(screen.getByLabelText("Price from")).toHaveValue("home_assistant_energy");
    expect(screen.queryByLabelText("Power sensors")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Price per kWh")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Lights on counts")).toHaveValue("home_assistant");
    expect(screen.getByLabelText("Alert at (lights on)")).toHaveValue(15);
  });

  it("edits picked power sensors and a fixed price", async () => {
    const user = await renderPage();

    await user.selectOptions(screen.getByLabelText("Power from"), "entities");
    await user.type(screen.getByLabelText("Power sensors"), "sensor.a,sensor.b");
    await user.selectOptions(screen.getByLabelText("Price from"), "fixed");
    await user.clear(screen.getByLabelText("Price per kWh"));
    await user.type(screen.getByLabelText("Price per kWh"), "0.1092");
    await save(user);

    expect(patches()[0].body).toEqual({
      energy_power_source: "entities",
      energy_power_entity_ids: "sensor.a,sensor.b",
      energy_price_source: "fixed",
      energy_price_per_kwh: "0.1092",
    });
  });

  it("hides the price when the power is off", async () => {
    const user = await renderPage();

    await user.selectOptions(screen.getByLabelText("Power from"), "off");

    expect(screen.queryByLabelText("Price from")).not.toBeInTheDocument();
  });

  it("edits the labels left out of the lights count and the alert threshold", async () => {
    const user = await renderPage();

    await user.type(screen.getByLabelText("Leave out lights labelled"), "exclude_from_whats_on");
    await user.clear(screen.getByLabelText("Alert at (lights on)"));
    await user.type(screen.getByLabelText("Alert at (lights on)"), "20");
    await save(user);

    expect(patches()[0].body).toEqual({ lights_on_exclude_labels: "exclude_from_whats_on", lights_on_alert_threshold: 20 });
  });

  it("counts only NSPanel Manager's lights without Home Assistant", async () => {
    await renderPage({ home_assistant_address: "", home_assistant_token_set: false, lights_on_source: "nspanelmanager" });

    expect(screen.queryByLabelText("Power from")).not.toBeInTheDocument();
    expect(screen.getByText(/The power and its cost come from Home Assistant/)).toBeInTheDocument();
    const lights = screen.getByLabelText("Lights on counts");
    expect(lights).toHaveValue("nspanelmanager");
    expect([...lights.querySelectorAll("option")].map((option) => option.getAttribute("value")).filter(Boolean)).toEqual(["nspanelmanager", "off"]);
    expect(screen.queryByLabelText("Leave out lights labelled")).not.toBeInTheDocument();
  });

  it("adds the energy card to the screensaver", async () => {
    const user = await renderPage({ screensaver_cards: "calendar:15" });

    await user.click(screen.getByRole("checkbox", { name: "Show energy card" }));
    await save(user);

    expect(patches()[0].body).toEqual({ screensaver_cards: "calendar:15,energy:10" });
  });
});
