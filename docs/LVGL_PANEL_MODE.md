# LVGL panel mode

Panel firmware with LVGL (firmware branch `test/lvgl-qemu-terminal`, `firmware_espidf/docs/LVGL.md`)
draws every page itself when the display runs an
[nspanel-terminal](https://github.com/ptaru/nspanel-terminal) TFT, and streams the pixels to it. On
NSPM's own Nextion TFT nothing changes. The firmware follows the TFT: install the terminal TFT and the
panel runs LVGL; install NSPM's TFT and it runs the Nextion pages again.

Until now the manager knew nothing about this. A panel was moved by hand: upload the terminal TFT
over a background slot (US "TFT 4"), point the panel at that slot, run a GUI update, and send
`lvgl_theme` / `lvgl_background` over MQTT. This document makes that a first-class panel setting.

## Summary of decisions

| Topic | Decision |
|---|---|
| Mode | Per-panel `display_mode` setting: `nextion` (default) or `lvgl` |
| Look | Per-panel `lvgl_theme` and `lvgl_background`; empty means "leave whatever the panel has" |
| Terminal TFTs | Two new files, one per layout (US portrait, EU landscape), stored under `/data`, separate from the four background slots |
| Which TFT is served | `lvgl` panels get the terminal TFT for their layout; `nextion` panels get their `selected_tft` slot as before. `selected_tft` is kept while in LVGL mode, so rollback is "switch back and update the GUI" |
| Detecting the TFT | md5 against every file the manager has staged or has ever been given (new `TftUpload` table), now; plus a firmware-reported `display_mode` in `NSPanelStatusReport`, which wins when present |
| Pushing the look | Both: new `NSPanelConfig` fields (sent today, used by firmware once it reads them) and the existing `lvgl_theme` / `lvgl_background` commands (work with today's firmware) |
| Screenshot | The settings page shows `http://<panel>/screenshot` straight from the panel, like the existing "open panel web page" link |
| Global defaults | Designed, not built (see "Later") |

## Data model

The panel's settings already live in `NSPanelSettings` (name/value rows, read by Django through
`settings_helper` and by MQTTManager through `NSPanel::_get_nspanel_setting_with_default`). The new
settings follow that convention, so MQTTManager reads them with no schema change on its side:

| Setting | Values | Default (absent) | Meaning |
|---|---|---|---|
| `display_mode` | `nextion`, `lvgl` | `nextion` | Which TFT the manager serves this panel, and so which UI it runs |
| `lvgl_theme` | `auto`, `dark`, `grey`, `ocean`, `dusk`, `aurora`, `peaks` | absent | LVGL palette. Absent: the manager never sends one |
| `lvgl_background` | `none`, `ocean`, `dusk`, `aurora`, `peaks` | absent | LVGL page background. Absent: never sent |

`light` is not offered: the firmware takes it as `grey`.

"Absent means unmanaged" matters for the first upgrade: Office, Kitchen, Lounge and Master Bathroom
already have a look set by hand over MQTT, and saving the panel settings form must not reset it. The
form's first option for both pickers is "Keep the panel's own".

`display_mode` is kept even in `nextion` mode, and `selected_tft` is kept in `lvgl` mode. Each mode
remembers its own choice, so switching is reversible.

One new model, `TftUpload` (migration `0073`), records every TFT the manager has been given:

| Field | |
|---|---|
| `md5` | Of the uploaded file |
| `kind` | `nextion` (a background slot) or `terminal` |
| `target` | The upload type: `eu1` .. `us4_horizontal_mirrored`, `terminal_us`, `terminal_eu` |
| `uploaded_at` | |

It exists for detection (next section): once a slot is overwritten, the md5 of what a panel still
runs would otherwise be unknown. MQTTManager does not use it.

## Detecting which TFT a panel runs

A panel reports `md5_tft_gui` in its status report and `md5_tft_file` at registration (stored on
`NSPanel.md5_tft_file`). The firmware sets this to the checksum of the TFT it last flashed, as given
by `checksum_tft_file/<id>`.

**Now (no firmware change): md5 lookup.** Django classifies a panel's md5 as:

1. the file currently staged in a slot or terminal location (computed from the files themselves), or
2. a file once uploaded (`TftUpload`), so a panel that was flashed with an earlier terminal build
   still reads "terminal TFT (older upload)", or
3. unknown (for example a TFT flashed before the manager kept a history, or one the manager shipped
   in the image, which is never "uploaded").

MQTTManager compares the panel's md5 with the file the panel's mode should run, exactly as it does
today for the slots, so an `lvgl` panel on a Nextion TFT, or the other way round, gets the existing
"GUI update available" warning.

md5 alone cannot tell whether LVGL is actually drawing: the panel may run the terminal TFT with
`lvgl_ui` switched off (the TFT then shows its own "waiting" page), or run firmware without LVGL at
all, which would leave the terminal TFT on its waiting page for good.

**Next (firmware change): a reported mode.** `NSPanelStatusReport` gains

```proto
enum NSPanelDisplayMode {
  DISPLAY_MODE_UNKNOWN = 0;  // Older firmware: the field is not sent
  DISPLAY_MODE_NEXTION = 1;  // NSPM's Nextion pages
  DISPLAY_MODE_LVGL = 2;     // LVGL draws through a terminal TFT
  DISPLAY_MODE_TERMINAL_IDLE = 3; // Terminal TFT, but LVGL is off (lvgl_ui false): the display shows the TFT's waiting page
}
NSPanelDisplayMode display_mode = 16;
string lvgl_theme = 17;       // As applied, after "light" -> "grey"; empty outside LVGL mode
string lvgl_background = 18;
```

When `display_mode` is not `UNKNOWN`, MQTTManager adds the warnings md5 cannot give: an `lvgl` panel
whose TFT is up to date but which reports `NEXTION` (the uploaded "terminal" TFT is not one), and any
panel reporting `TERMINAL_IDLE` (the display is stuck on the waiting page). A disagreement md5 can see,
such as a `nextion` panel still on the terminal TFT, already shows as "GUI update available". The
reported mode, theme and background are in the panel's websocket status (`display_mode`,
`lvgl_theme`, `lvgl_background`, next to `display_mode_setting`), and the settings page shows the mode.

Why both: md5 works for every panel in the field today and is what decides whether to offer a GUI
update. The reported mode is the only thing that proves LVGL is drawing, and it is cheap for the
firmware (it already logs the decision in `LvglUi::init()`). The proto change is in this branch, so
the manager handles the field the day firmware sends it; older firmware never sends it, and the
manager reads `0` as "not reported".

## Pushing the theme and background

Two ways, with different tradeoffs:

| | `NSPanelConfig` fields | MQTT commands (`lvgl_theme`, `lvgl_background`) |
|---|---|---|
| Works with today's firmware | No: firmware must read the fields | Yes |
| Survives re-provisioning, NVS loss, a replaced panel | Yes: the retained config is re-read on every boot | Only if the manager resends |
| Source of truth | The manager | The panel's NVS, last command wins |
| Cost on the panel | None when unchanged (the firmware can compare) | Each command writes NVS and repaints |

**Recommendation: config fields as the mechanism, commands as the bridge.** The manager does both:

- `NSPanelConfig` gains `string lvgl_theme = 49;` and `string lvgl_background = 50;`, filled from the
  panel's settings on every config push. Empty means "not managed". Older firmware ignores unknown
  fields, so sending them is safe now.
- MQTTManager also sends the existing commands on `nspanel/<MAC>/command`, but only to panels in
  `lvgl` mode and only when needed: when a reload changes the panel's theme or background, or moves
  the panel into `lvgl` mode (all of the look, for a panel that already runs the terminal TFT), and
  after `register_accept` the first time a panel registers after the manager starts (which also covers a panel re-provisioned
  while the manager was down). Not on every reconnect: weak-signal panels reconnect often, and each
  command is an NVS write and a full repaint.

When the fleet runs firmware that reads the config fields, the commands become redundant but
harmless (with the firmware change below they are no-ops when nothing changed); they can be dropped a
release or two later, the same way the name-based command topic is being phased out.

The kill switch `lvgl_ui` is not a manager setting. The way back to the Nextion pages is to switch the
panel to `nextion` and update its GUI, which leaves no hidden state on the panel. `lvgl_ui` stays an
emergency tool for a panel whose terminal TFT is broken and cannot be reflashed.

## TFT provisioning

### Files

Terminal TFTs get their own upload types, separate from the four background slots:

| Upload type | Stored at | Served to |
|---|---|---|
| `terminal_us` | `/data/tft/terminal/us/gui.tft` | `lvgl` panels with `is_us_panel` true |
| `terminal_eu` | `/data/tft/terminal/eu/gui.tft` | `lvgl` panels with `is_us_panel` false |

Per layout, not per orientation: the firmware chooses its LVGL layout and terminal receiver from
`is_us_panel` alone (`LvglRenderer::_config_event_handler`, `NextionTerminal::options_for`). The US
layout uses the US receiver (320x480, `terminal_us_state2.py`), the EU layout uses nspanel-terminal's
`terminal-eu.tft` (454x320). LVGL ignores `us_panel_orientation`, so a US panel set to a horizontal
orientation still gets the portrait US layout; the settings page says so.

Under `/data` rather than next to the slots (`HMI_files/tft_automation/...` inside the image):
the slots ship NSPM's own TFTs, so losing an upload there on an image update falls back to a
working TFT. Nothing ships a terminal TFT, so the same loss would leave every LVGL panel with no file
behind `checksum_tft_file` (404). `/data` is the volume that already holds the database.

The upload modal lists the two new types under "Terminal TFT (LVGL mode)". `nspm-mcp`'s `upload_gui`
and any script that posts `tft_file_type` keep working; they gain two values.

### Switching a panel

1. Upload the terminal TFT for the panel's layout (once).
2. On the panel's settings page choose **Display: LVGL (terminal TFT)**, optionally a theme and a
   background, and save.
3. The manager now serves the terminal TFT for that panel; the panel's status shows "GUI update
   available". Press **Update GUI** (the existing button and flow, `tft_update` command).
4. The panel flashes the TFT, reboots, detects the terminal receiver and starts LVGL with the look it
   was sent.

The settings page does not start the GUI update by itself: a TFT update takes minutes, blanks the
display, and the user may want to set several panels first. It says that an update is needed.

### Rollback

Choose **Display: Nextion (NSPM TFT)**, save, and update the GUI. The panel's `selected_tft` slot
was never changed, so it gets the background it had before. The firmware follows the TFT back to the
Nextion pages.

If the terminal TFT will not start (the display sits on its waiting page), the panel still takes
MQTT and TFT updates (LVGL.md), so the same rollback works.

### Migrating the existing installation

Lounge, Office, Kitchen and Master Bathroom run the terminal TFT from the US "TFT 4" slot
(md5 `ee73878729a0757704a86d136ddcdf33`).

1. Upload that same file as `terminal_us`. The md5 is unchanged, so these panels need no reflash.
2. Set each of them to `lvgl` and set their `selected_tft` back to `tft1` (NSPM's TFT), so a later
   rollback lands on a real Nextion TFT. Their status shows no GUI update pending.
3. Re-upload NSPM's US TFT 4 into the US TFT 4 slot, or leave the slot unused.

## Settings page

A **Display** card on `/nspanel/<id>`:

- **Display mode**: Nextion (NSPM TFT) / LVGL (terminal TFT). The background-slot picker and its
  preview belong to Nextion mode and are hidden in LVGL mode.
- **Theme** and **Background** pickers (LVGL mode only), each with "Keep the panel's own" first.
- **Running now**: what the panel's last registered md5 is ("Terminal TFT (US, staged)", "NSPM TFT
  slot 1 (US)", "Terminal TFT (older upload)", "Unknown"), and the reported display mode when the
  firmware sends one.
- Notes when they apply: the terminal TFT for this layout has not been uploaded; LVGL ignores the
  US horizontal orientations; a GUI update is needed after changing the mode.
- **Screen preview** (LVGL mode only): `<img src="http://<panel-ip>/screenshot?format=png">` with a
  Refresh button. The IP comes from the panel's websocket status, which the page already receives.

The screenshot is loaded by the browser from the panel, as the existing "open the panel's web page"
link does, rather than proxied by Django: Django does not know panel IPs (MQTTManager does, at
runtime) and the panel's server has no auth either way. Limits: a browser on another subnet than the
panel, or a manager page served over HTTPS (Home Assistant ingress), cannot load it; the page then
shows "Screenshot unavailable". A proxy through MQTTManager (which knows the IP) is the fix if that
matters; see "Later".

## Backwards compatibility

- Panels without the new settings behave exactly as before: `display_mode` defaults to `nextion`,
  the slot logic is unchanged, nothing new is sent except two empty config fields.
- Older firmware ignores the new `NSPanelConfig` fields (protobuf unknown fields) and never sends the
  new status fields (they read as `UNKNOWN` / empty).
- Firmware without LVGL that receives `lvgl_*` commands logs `Unknown command` and carries on. The
  manager only sends them to `lvgl` panels, so this only happens if a panel is put in LVGL mode
  before its firmware supports it, which is a real risk: that panel's display then sits on the
  terminal TFT's waiting page until it is switched back. Until the firmware reports
  `display_mode`, the manager cannot tell; the settings page warns that LVGL mode needs LVGL firmware.
- `checksum_tft_file/<id>` and `download_tft/<id>` keep their URLs and answer for whichever TFT the
  panel's mode selects, so firmware needs no change to fetch the terminal TFT.

## Firmware follow-up (branch `test/lvgl-qemu-terminal`)

1. **Protobuf.** Regenerate `lib/ProtoBuf/protobuf_nspanel.pb-c.{c,h}` from this branch's
   `docker/protobuf/protobuf_nspanel.proto` (or copy `protobuf_firmware/`). New fields:
   `NSPanelConfig.lvgl_theme` (49), `NSPanelConfig.lvgl_background` (50),
   `NSPanelStatusReport.display_mode` (16), `.lvgl_theme` (17), `.lvgl_background` (18).
2. **Apply the look from the config.** In the config event handler (next to
   `LvglRenderer::_config_event_handler`, or in `LvglUi`): for each of `lvgl_theme` and
   `lvgl_background`, if the config's string is non-empty and differs from `ConfigManager`'s, store
   it, `ConfigManager::save_config()` once, then `LvglUi::set_look()` once. Empty: leave the saved
   value. Keep saving to NVS so the boot screen uses the look before the config arrives.
3. **Make the commands idempotent.** In `UpdateManager` `lvgl_theme` / `lvgl_background`: compare
   with the saved value first, and skip the NVS write and `set_look()` when unchanged (and treat
   `light` as `grey` before comparing).
4. **Report the mode.** In `StatusUpdateManager`, set `display_mode`: `LVGL` when
   `LvglUi::active()`; `TERMINAL_IDLE` when the display is a terminal receiver
   (`NextionTerminal::is_receiver()` on the boot identity) but `ConfigManager::lvgl_ui` is false;
   `NEXTION` otherwise (NSPM flag received). Set `lvgl_theme` / `lvgl_background` to the applied
   values (`grey` for `light`) in LVGL mode, empty otherwise. `LvglUi::init()` already makes this
   decision; keep its result in a static the status task can read.
5. **Screenshot CORS (optional).** Add `Access-Control-Allow-Origin: *` to `/screenshot` responses
   (including 409/503) so the settings page can `fetch()` it and tell "Nextion pages" (409) from "busy"
   (503) and "unreachable"; with a plain `<img>` it can only tell success from failure.
6. **Orientation (optional, product decision).** LVGL ignores `us_panel_orientation`. If horizontal
   US panels should run LVGL in landscape, the layout choice has to take orientation into account,
   and the manager would then key terminal TFTs by layout rather than by `is_us_panel`.

## Later

- **Global defaults** for theme and background (Settings rows `lvgl_theme`, `lvgl_background`, with
  a per-panel "Use global" choice, as `screensaver_mode` does). Needs the React settings page
  (`/rest/v2/settings`) and an `MQTT_MANAGER_SETTING` entry for each; per-panel covers today's need.
- **Screenshot proxy** in MQTTManager (`GET /nspanel/<mac>/screenshot` relaying to the panel's IP),
  for HTTPS/ingress and for browsers that cannot reach the panel subnets.
- **A "switch and update" action** that saves the mode and starts the GUI update in one step, once
  the reported `display_mode` lets the manager confirm the result.
- **Drop the `lvgl_*` commands** once the fleet's firmware reads the config fields.
