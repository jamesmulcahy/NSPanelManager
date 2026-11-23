# Display

Every panel draws its UI with LVGL. The panel firmware renders each page itself and streams the pixels to an
[nspanel-terminal](https://github.com/ptaru/nspanel-terminal) TFT on the display (firmware
`firmware_espidf/docs/LVGL.md`). There is one display mode and nothing to choose: the manager serves each
panel the terminal TFT for its layout, and a panel's look (theme and background) is a per-panel setting.

NSPM's Nextion HMI pages, with their per-theme TFTs and background slots, were removed in the Nextion removal
(`NEXTION_REMOVAL_PLAN.md`; the last manager and firmware that still had them are tagged `last-nextion`). The
Nextion *display* is still what the panel has: its serial driver and the TFT upload path stay, and the terminal
TFT is installed through them.

## Summary

| Topic | How it works |
|---|---|
| Display mode | LVGL on the terminal TFT, always. The `display_mode` setting is read-only: REST v2 reports `lvgl`, accepts `lvgl` and rejects `nextion` with a 400 that says why. Migration `0076` wrote `display_mode=lvgl` for every panel; a stale `nextion` row (a rollback to an older manager can write one) is ignored |
| Terminal TFTs | One per layout: US portrait (`terminal_us`) and landscape (`terminal_eu`). The image bundles both; an upload replaces the bundled file for its layout |
| Layout | From the panel type and orientation: US vertical gets the US layout, every other panel gets landscape (see "Orientation") |
| Look | Per-panel `lvgl_theme` and `lvgl_background`; empty means "leave whatever the panel has" |
| Detecting the TFT | md5 of the TFT the panel reports against the files the manager has staged or been given (`TftUpload`), plus the firmware-reported `display_mode`, which wins when present |
| Legacy screen | A panel on NSPM's old HMI TFT, with new firmware, shows "Display update needed" until its GUI is updated (see "Panels still on the HMI TFT") |
| Screenshot | The settings page shows `http://<panel>/screenshot` straight from the panel |

## Panels still on the HMI TFT

A panel that was running NSPM's own Nextion TFT (the old default) needs the terminal TFT. Firmware from the
Nextion removal onwards cannot draw anything on the old TFT, so it shows a **legacy screen** and waits: the
HMI TFT's own loading page, with the main line "Display update needed" and a second line with what the panel
knows (panel name, IP address, "Update GUI in NSPanel Manager"; shortened to fit, blank until the panel has
a network). MQTT, relays, the physical buttons, the temperature sensor and firmware updates keep working
throughout, and the `tft_update` command still installs a TFT.

Installing is **manual**; the manager never sends it by itself:

1. The panel registers with the feature `no_hmi` and reports `DISPLAY_MODE_NEXTION` (the legacy screen). If
   the firmware misses the TFT's banner during its short wait it lands in `TERMINAL_IDLE` with a blank
   screen instead; the manager treats that as the legacy screen too, unless the panel's TFT md5 is a terminal
   TFT it knows.
2. The manager flags the panel on the panel list and the panel page with the warning **"Shows the legacy
   screen — press Update GUI"**, with the button next to it. This needs the terminal TFT for the panel's
   layout to be staged, which the bundled files guarantee.
3. Press **Update GUI** (the same `tft_update` flow as any GUI update). The panel flashes the terminal TFT,
   reboots, detects the receiver and starts LVGL with the look it is sent.

Safety gates and edge cases:

- **Firmware first.** A GUI update is refused for a panel whose `register_request` lacks the `lvgl_look`
  feature, or that reports no `display_mode`: such firmware predates LVGL, and the terminal TFT would leave it
  on the waiting page for good. The panel shows "Update the firmware first"; the firmware update brings it to
  the point above.
- **A panel that has the staged TFT but still reports a legacy display** gets a warning to check that the
  uploaded TFT is an nspanel-terminal TFT.
- **`TERMINAL_IDLE` on a known terminal TFT** means LVGL is not running (it failed to start), so the display
  only shows the TFT's waiting page. A firmware update fixes it.
- **Rolling back the manager** to `last-nextion` keeps every panel in LVGL mode, because the migration wrote
  `display_mode=lvgl` rather than deleting rows, so the old manager serves the terminal TFT and does not offer
  the HMI TFT as a GUI update. Rolling back a panel's firmware to `last-nextion` is fine on the terminal TFT.
- **Old manager, new firmware, HMI TFT**: legacy screen. A `last-nextion` manager ignores `no_hmi`, so press
  Update GUI yourself; if the panel was set to `nextion` there, set it to LVGL first, or the update
  reinstalls the HMI TFT (still the legacy screen). Upstream NSPM is not supported with this firmware: the panel
  stays controllable over MQTT, nothing more.
- The `nspm-mcp` `upload_gui` and the TFT upload dialog take only the terminal types (`terminal_us`,
  `terminal_eu`); the old slot types are rejected.

## Orientation and layout

The terminal TFT is chosen by layout, from the panel type and `us_panel_orientation`:

| Panel | Layout | TFT served | `is_us_panel` sent to the firmware |
|---|---|---|---|
| EU | Landscape | `terminal_eu` | false |
| US, vertical | Portrait | `terminal_us` | true |
| US, horizontal | Landscape | `terminal_eu` (on US hardware) | false |

A US panel mounted sideways runs the EU terminal TFT with the landscape layout, as the firmware's QEMU
`eu-on-us` terminal does. The settings page says so, and changing the panel type or orientation switches the
layout as soon as you save; press Update GUI to install the matching TFT.

**Mirrored was removed.** The old "US Horizontal (Mirrored)" option is gone and migration 0077 turned any panel
that used it into plain horizontal. The firmware has no rotate or mirror path. The EU
terminal TFT has not been run on a real EU panel here, and the fleet is all US portrait, so landscape is
covered by QEMU only.

## Data model

The panel's settings live in `NSPanelSettings` (name/value rows, read by Django through `settings_helper` and
by MQTTManager through `NSPanel::_get_nspanel_setting_with_default`).

| Setting | Values | Default (absent) | Meaning |
|---|---|---|---|
| `lvgl_theme` | `auto`, `dark`, `grey`, `ocean`, `dusk`, `aurora`, `peaks`, `vesuvius`, `parthenon` | absent | LVGL palette. Absent: the manager never sends one |
| `lvgl_background` | `none`, `ocean`, `dusk`, `aurora`, `peaks`, `vesuvius`, `parthenon` | absent | LVGL page background. Absent: never sent |
| `us_panel_orientation` | `vertical`, `horizontal` | `vertical` | Picks the layout (above) |

`light` is not offered: the firmware takes it as `grey`. "Absent means unmanaged": saving the panel settings
form must not reset a look set on the panel, so the form's first option for both pickers is "Keep the panel's
own".

`TftUpload` records every TFT the manager has been given (`md5`, `kind`, `target`, `uploaded_at`). It exists
for detection: once an upload is replaced, the md5 of what a panel still runs would otherwise be unknown.
Rows with `kind` `nextion` are uploads of NSPM's old HMI TFTs; they stay, so such a panel reads "NSPM TFT slot 1
(US), an older upload" rather than "Unknown".

## Detecting which TFT a panel runs

A panel reports `md5_tft_gui` in its status report and `md5_tft_file` at registration (stored on
`NSPanel.md5_tft_file`): the checksum of the TFT it last flashed. Django classifies it as:

1. the terminal TFT currently staged for either layout (an upload, else the bundled file; the bundled one is
   labelled "bundled"), or
2. a file once uploaded (`TftUpload`), labelled "an older upload", or
3. unknown (a TFT flashed before the manager kept a history).

MQTTManager compares the panel's md5 with the terminal TFT for its layout, and a difference gives the
"GUI update available" warning.

md5 alone cannot tell whether LVGL is drawing, so `NSPanelStatusReport` carries the firmware's own answer:

```proto
enum NSPanelDisplayMode {
  DISPLAY_MODE_UNKNOWN = 0;  // Older firmware: the field is not sent
  DISPLAY_MODE_NEXTION = 1;  // The legacy screen: NSPM's old HMI TFT is installed
  DISPLAY_MODE_LVGL = 2;     // LVGL draws through a terminal TFT
  DISPLAY_MODE_TERMINAL_IDLE = 3; // Terminal TFT, but LVGL is not running: the display shows the TFT's waiting page
}
NSPanelDisplayMode display_mode = 16;
string lvgl_theme = 17;       // As applied, after "light" -> "grey"; empty outside LVGL
string lvgl_background = 18;
```

`DISPLAY_MODE_NEXTION` keeps its name on the wire for compatibility; it now means "legacy HMI TFT". Older
firmware never sends the field and the manager reads `0` as "not reported". The reported mode, theme and
background are in the panel's websocket status (`display_mode`, `lvgl_theme`, `lvgl_background`), and the
settings page shows the mode.

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

The firmware's old `lvgl_ui` kill switch is not a manager setting, and current firmware ignores a saved
`lvgl_ui: false`: with no Nextion pages to fall back to, switching LVGL off would only blank the screen.

## A look chosen on the panel

LVGL firmware (`firmware_espidf/docs/LVGL.md`, "The look") has a look
picker in the swipe-down menu: eight background + palette combinations (Ocean, Dusk, Aurora, Peaks, Vesuvius and Parthenon
with `theme: auto`; Dark and Grey with `background: none`). A pick must become the panel's configured
look, so the settings page shows it and the next config push does not undo it.

### Protocol

| | |
|---|---|
| Panel → manager | `NSPanelMQTTManagerCommand` with `lvgl_look` (`LvglLook { theme, background }`, oneof field 11) on the manager's protobuf command topic, like every other panel action. Sent on a pick and on an `lvgl_theme` / `lvgl_background` command (from the MCP, say), and again while unconfirmed (below) |
| Manager → panel | Nothing new: the confirmation is an ordinary `NSPanelConfig` push whose fields 49/50 equal the reported look |
| Capability | `register_request` gains `"features": ["lvgl_look"]` |

**Why a command** and not the status report or a topic of its own:

- The status report's `lvgl_theme` / `lvgl_background` (17/18) say what the panel *draws*, not that
  someone *chose* it. After the manager changed the look while a panel was offline, the panel's first
  status reports still carry the old look; persisting those would revert the manager's change. A
  report is an event, so it is a command, like the panel's other actions.
- On the protobuf command topic an older manager parses the command, finds no oneof case it knows,
  and every `CommandManager` callback passes it by: nothing is logged or done. (The JSON topic,
  `nspanel/mqttmanager/command`, would not do: an older manager logs `Got command but no handler for it
  exists` at ERROR for anything but `register_request`, and the panel resends while unconfirmed.)
- No topic to subscribe to per panel; the command reaches `NSPanel::command_callback`, which acts on it
  only when `nspanel_id` is its own.

**What MQTTManager does** (`NSPanel::_handle_lvgl_look_report`, from `command_callback`): checks the
names against the values the firmware draws (`auto dark grey ocean dusk aurora peaks vesuvius parthenon`,
`none ocean dusk aurora peaks vesuvius parthenon`, the same lists as `display_mode.LVGL_THEMES` / `LVGL_BACKGROUNDS`);
ignores a panel awaiting accept or denied; writes both rows with
`MqttManagerConfig::set_nspanel_setting_value()` (update or insert, the name/value rows Django owns, so
no migration; the database's busy timeout covers a concurrent save in the web interface); sets its
in-memory look to match, so the next `reload_config()` sees no change and sends nothing back; then
pushes the config (the confirmation, which also replaces the retained config that still had the old
look) and a websocket status update. Both settings are written even if only one changed, so a panel
whose look was "Keep the panel's own" becomes managed with what it shows. A malformed or unknown look,
or a failed database write, is logged and not confirmed (the panel keeps its look and asks again).
This happens in either display mode setting.

### Conflicts and loops

The panel keeps a reported look **unconfirmed** (saved on the panel) until a config with the same look
arrives. While unconfirmed it does not apply a config with a different look, and answers it by
reporting again, at most every 10 s. Cases (new firmware, new manager):

| Sequence | Result |
|---|---|
| Pick; report; manager saves, pushes config with the pick | Confirmed. One round trip, one flash write on the panel |
| Pick crosses a settings save in the web UI (config with the old look arrives first) | The stale config is ignored and the pick reported again; the report then overwrites the web save. Last writer at the panel wins |
| Pick while MQTT is down, or the manager is down | Unconfirmed survives; after reconnecting, the retained config (old look) is ignored, the report sent; the manager saves it when it is up. A change made in the manager meanwhile loses (the panel cannot tell which was later) |
| Manager restarts | Panel re-registers. A panel that lists `lvgl_look` gets **no** `lvgl_theme` / `lvgl_background` commands (only the config): a command sent on registration would overtake a report still in flight, and commands are not answers to anything |
| Manager changes the look (settings save) when nothing is pending | Config push; the panel applies it; no report (nothing changed on the panel) |
| Report → save → config: could it ping-pong? | No. A config never triggers a report unless the panel is unconfirmed *and* the config differs; the manager answers a valid report with exactly that look, so the second step always confirms. The manager answers an invalid report with nothing. The 10 s spacing bounds any remaining mismatch (e.g. a manager that rewrote names) to one message per 10 s, not a loop |
| A save in the web UI with a stale form (opened before the pick) | Overwrites the pick, as any later explicit save does. The page says so next to the pickers |

### Compatibility

| Firmware | Manager | Behaviour |
|---|---|---|
| New | New | As above |
| New | A manager with fields 49/50 and commands but no report | Picks work and survive reboots. The report is published to a topic nobody reads. The panel stays unconfirmed, so configs carrying the manager's look are ignored; a command (sent when the look is changed in the manager, and once per manager start) replaces the pick. Leaving the panel on "Keep the panel's own" keeps picks |
| New | Upstream NSPM (no 49/50) | Picks work and survive reboots; the config's empty fields never replace them; no log noise |
| Old (no `features`) | New | Exactly as before: never reports; the manager keeps sending commands as before |
| Legacy screen (the panel still runs NSPM's old HMI TFT) | Any | No menu item and no page, because LVGL is not drawing. The look is stored and applied once the terminal TFT is installed |

Payload sizes: the report is under 60 bytes; `NSPanelConfig` grows by two short strings (~20 bytes);
the firmware's MQTT buffer is 4 KB.

## TFT provisioning

### Files

| Upload type | Stored at | Served to |
|---|---|---|
| `terminal_us` | `/data/tft/terminal/us/gui.tft` | US vertical panels |
| `terminal_eu` | `/data/tft/terminal/eu/gui.tft` | Every other panel |

Uploads live under `/data`, the volume that already holds the database, so they survive an image update.

**Bundled terminal TFTs.** The image ships one terminal TFT per layout, in `HMI_files/terminal/{us,eu}/gui.tft`
(provenance, checksums and how the US file is built: `HMI_files/terminal/README.md`). A layout with no upload
is served its bundled file (`display_mode.staged_terminal_tft_file()`; MQTTManager falls back the same way when
it computes the checksum), so a new install needs no upload and a removed upload falls back to a working TFT.
An upload replaces the bundled file for its layout. The settings page names a panel running the bundled file
"Terminal TFT (US), bundled". These are the only HMI-directory files left in the image.

The TFT upload dialog lists the two types under "Terminal TFT".

### Installing and updating

A new panel needs no display setup: flash the firmware, add the panel, and press **Update GUI** if the panel
asks for one (a fresh Sonoff display, or any panel on a different TFT). The settings page's **Display** card
shows what the panel runs now ("Terminal TFT (US), bundled", "Unknown TFT (...)"), the mode the firmware reports,
and a note when the display image is not the one its layout needs. The settings page does not start a GUI update
by itself: it takes minutes and blanks the display, and you may want to set several panels first.

## Settings page

A **Display** card on `/nspanel/<id>`:

- **Running now**: the panel's last registered md5 as a label, and the reported display mode when the
  firmware sends one ("LVGL", "legacy screen (its GUI needs updating)", "terminal TFT with LVGL off").
- **Theme** and **Background** pickers, each with "Keep the panel's own" first.
- Notes when they apply: no terminal TFT is available for this layout; a sideways US panel runs the landscape
  layout; the display image does not match the layout, so press Update GUI.
- **Screen preview**: `<img src="http://<panel-ip>/screenshot?format=png">` with a Refresh button. The IP comes
  from the panel's websocket status. A panel on the legacy screen has no screenshot (the firmware answers 409).

The screenshot is loaded by the browser from the panel, like the "open the panel's web page" link, rather than
proxied by Django: Django does not know panel IPs (MQTTManager does, at runtime) and the panel's server has no
auth either way. A browser on another subnet than the panel, or a manager page served over HTTPS (Home
Assistant ingress), cannot load it; the page then says "Screenshot unavailable".

## Backwards compatibility

- Older firmware ignores the `NSPanelConfig` look fields (protobuf unknown fields) and never sends the status
  fields (they read as `UNKNOWN` / empty).
- Firmware that predates LVGL cannot run the terminal TFT; the `lvgl_look` gate above stops the manager from
  installing it there.
- `checksum_tft_file/<id>` and `download_tft/<id>` keep their URLs and answer with the panel's terminal TFT, so
  firmware needs no change to fetch it.
- The protobuf keeps its HMI-shaped fields (Nextion colours, font glyphs, 4/8/12 page types) until the layout
  protocol is replaced; LVGL decodes them.

## Later

- **Global defaults** for theme and background (Settings rows `lvgl_theme`, `lvgl_background`, with a per-panel
  "Use global" choice, as `screensaver_mode` does). Needs the React settings page (`/rest/v2/settings`) and an
  `MQTT_MANAGER_SETTING` entry for each.
- **Rotation** in the firmware (draw and touch turned 180 degrees), which would bring back a mirrored option.
- **Screenshot proxy** in MQTTManager (`GET /nspanel/<mac>/screenshot` relaying to the panel's IP), for HTTPS
  ingress and for browsers that cannot reach the panel subnets.
- **Drop the `lvgl_*` commands** once the fleet's firmware reads the config fields. Panels listing the
  `lvgl_look` feature already get none.
- **Live settings page.** The page shows the look as of when it was loaded; it could follow the websocket
  status and update its pickers.
