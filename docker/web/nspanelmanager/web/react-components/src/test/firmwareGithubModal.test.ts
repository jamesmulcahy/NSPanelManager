import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../../../static/firmware_github.js";

// The "Firmware from GitHub" modal's script, run against the ids in templates/modals.html and a fake C2 server.
declare global {
  interface Window {
    firmwareGithub: { open: () => Promise<void>; load: () => Promise<void>; stage: () => Promise<void>; pick: () => Promise<void> };
  }
}

const MODAL = `
<dialog id="firmware_github_modal" data-api-base="/ingress/rest/v2/firmware">
  <span id="fwgh_repo"></span><span id="fwgh_release"></span>
  <div id="fwgh_error" class="hidden"></div>
  <table><tbody id="fwgh_table_body"></tbody></table>
  <select id="fwgh_release_select"><option value="">Latest</option></select>
  <div id="fwgh_result" class="hidden"></div>
  <span id="fwgh_spinner" class="hidden"></span>
  <button id="fwgh_refresh_button"></button><button id="fwgh_stage_button"></button>
</dialog>`;

const status = (overrides: Record<string, unknown> = {}) => ({
  repo: "owner/fw",
  release: "latest",
  resolved: { tag: "build-bbbbbbbb", commit: "b".repeat(40), boards: { sonoff: { md5: "new1", size: 1 }, custom: { md5: "same2", size: 1 } } },
  staged: {
    sonoff: { md5: "old1", source: "github", tag: "build-aaaaaaaa", commit: "a".repeat(40), staged_at: null },
    custom: { md5: "same2", source: null, tag: null, commit: null, staged_at: null },
  },
  up_to_date: { sonoff: false, custom: true },
  releases: [{ tag: "build-bbbbbbbb", commit: "b".repeat(40), built_at: "2026-11-19T12:00:00Z" }],
  error: null,
  ...overrides,
});

const text = (id: string) => document.getElementById(id)!.textContent;
const hidden = (id: string) => document.getElementById(id)!.classList.contains("hidden");
let calls: { url: string; init?: RequestInit }[];
let replies: Record<string, { status: number; body: unknown }>;

beforeEach(() => {
  document.body.innerHTML = MODAL;
  (document.getElementById("firmware_github_modal") as HTMLDialogElement).showModal = vi.fn();
  document.cookie = "csrftoken=token-123";
  calls = [];
  replies = {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const reply = replies[`${init?.method ?? "GET"} ${url.split("?")[0]}`];
      return new Response(JSON.stringify(reply.body), { status: reply.status });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("opening", () => {
  it("shows the staged and available builds per board with the releases", async () => {
    replies["GET /ingress/rest/v2/firmware"] = { status: 200, body: status() };
    await window.firmwareGithub.open();

    expect(calls[0].url).toBe("/ingress/rest/v2/firmware?releases=1");
    expect(text("fwgh_repo")).toBe("owner/fw");
    const rows = [...document.querySelectorAll("#fwgh_table_body tr")].map((row) => row.textContent);
    expect(rows[0]).toContain("Sonoff original NSPanel");
    expect(rows[0]).toContain("old1");
    expect(rows[0]).toContain("build-aaaaaaaa");
    expect(rows[0]).toContain("new1");
    expect(rows[0]).toContain("behind");
    expect(rows[1]).toContain("✓");
    expect([...(document.getElementById("fwgh_release_select") as HTMLSelectElement).options].map((o) => o.value)).toEqual(["", "build-bbbbbbbb"]);
    expect((document.getElementById("fwgh_stage_button") as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows a GitHub error returned with a 200", async () => {
    replies["GET /ingress/rest/v2/firmware"] = { status: 200, body: status({ resolved: null, up_to_date: null, error: { code: "rate_limited", message: "Try later." } }) };
    await window.firmwareGithub.open();

    expect(hidden("fwgh_error")).toBe(false);
    expect(text("fwgh_error")).toContain("Try later.");
    expect(text("fwgh_error")).toContain("rate_limited");
    expect(document.querySelectorAll("#fwgh_table_body tr")).toHaveLength(2);
  });
});

describe("staging", () => {
  beforeEach(async () => {
    replies["GET /ingress/rest/v2/firmware"] = { status: 200, body: status() };
    await window.firmwareGithub.open();
    calls = [];
  });

  it("re-fetches the chosen release when the picker changes, without the list", async () => {
    const select = document.getElementById("fwgh_release_select") as HTMLSelectElement;
    select.value = "build-bbbbbbbb";
    replies["GET /ingress/rest/v2/firmware"] = { status: 200, body: status({ release: "build-bbbbbbbb", releases: undefined, resolved: { tag: "build-bbbbbbbb", commit: "b", boards: { sonoff: { md5: "pinned1", size: 1 }, custom: { md5: "pinned2", size: 1 } } } }) };
    await window.firmwareGithub.pick();

    expect(calls[0].url).toBe("/ingress/rest/v2/firmware?release=build-bbbbbbbb");
    expect(text("fwgh_release")).toBe("build-bbbbbbbb");
    expect(text("fwgh_table_body")).toContain("pinned1");
    expect(select.options).toHaveLength(2);
    expect(select.value).toBe("build-bbbbbbbb");

    select.value = "";
    await window.firmwareGithub.pick();
    expect(calls[1].url).toBe("/ingress/rest/v2/firmware");
  });

  it("posts the chosen release with the CSRF token and shows before and after", async () => {
    (document.getElementById("fwgh_release_select") as HTMLSelectElement).value = "build-bbbbbbbb";
    replies["POST /ingress/rest/v2/firmware/stage"] = {
      status: 200,
      body: { tag: "build-bbbbbbbb", commit: "b".repeat(40), boards: { sonoff: { before_md5: "old1", after_md5: "new1", changed: true }, custom: { before_md5: "same2", after_md5: "same2", changed: false } } },
    };
    await window.firmwareGithub.stage();

    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({ release: "build-bbbbbbbb" });
    expect((calls[0].init?.headers as Record<string, string>)["X-CSRFToken"]).toBe("token-123");
    expect(text("fwgh_result")).toContain("old1 → new1");
    expect(text("fwgh_result")).toContain("already staged");
    expect(calls[1].url).toBe("/ingress/rest/v2/firmware?releases=1&release=build-bbbbbbbb");
    expect((document.getElementById("fwgh_stage_button") as HTMLButtonElement).disabled).toBe(false);
  });

  it("omits the release for Latest", async () => {
    replies["POST /ingress/rest/v2/firmware/stage"] = { status: 200, body: { tag: "t", commit: "c", boards: { sonoff: { before_md5: "x", after_md5: "x", changed: false }, custom: { before_md5: "y", after_md5: "y", changed: false } } } };
    await window.firmwareGithub.stage();

    expect(JSON.parse(calls[0].init?.body as string)).toEqual({});
  });

  it("shows a failed stage as an error and no result", async () => {
    replies["POST /ingress/rest/v2/firmware/stage"] = { status: 502, body: { error: { code: "verification_failed", message: "Wrong chip.", board: "custom" } } };
    await window.firmwareGithub.stage();

    expect(text("fwgh_error")).toContain("Wrong chip.");
    expect(text("fwgh_error")).toContain("custom");
    expect(hidden("fwgh_result")).toBe(true);
    expect((document.getElementById("fwgh_stage_button") as HTMLButtonElement).disabled).toBe(false);
  });

  it("disables the button while the request is in flight", async () => {
    let release: (response: Response) => void = () => {};
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => (release = resolve))));
    const pending = window.firmwareGithub.stage();

    expect((document.getElementById("fwgh_stage_button") as HTMLButtonElement).disabled).toBe(true);
    release(new Response(JSON.stringify({ error: { code: "download_failed", message: "No." } }), { status: 502 }));
    await pending;
    expect((document.getElementById("fwgh_stage_button") as HTMLButtonElement).disabled).toBe(false);
  });
});
