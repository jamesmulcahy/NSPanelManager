# Terminal TFTs

The nspanel-terminal TFTs a panel in LVGL mode runs (docs/LVGL_PANEL_MODE.md): with one of these on its
display, the panel's firmware draws every page with LVGL and streams the pixels to it. The manager serves
these when nothing was uploaded for that layout (`terminal_us` / `terminal_eu` in the TFT upload dialog);
an upload replaces them for that layout until it is removed from `/data/tft/terminal/`.

Both come from [nspanel-terminal](https://github.com/ptaru/nspanel-terminal) (MIT; see `LICENSE` and
`NOTICE` here, which apply to these files). The firmware accepts any receiver that reports native version
94 to 127 (`NextionTerminal::is_receiver`).

| File | Native | MD5 | SHA-256 | From |
|---|---|---|---|---|
| `us/gui.tft` | 98 | `ee73878729a0757704a86d136ddcdf33` | `80fc1be959ff5b550560632e763f4a1cb19dbdec38de8ffa5ac28111b3b4f828` | Our build (below) |
| `eu/gui.tft` | 95 | `c873a214b53a10269138c6c81b9ee57e` | `95c4b8319a01b8a76f14f695b02f7921bde21aa1f8b7d2bd3a43ef89336e56e8` | nspanel-terminal `45deb5f`, `firmware/terminal-eu.tft` as committed (its `.sha256` matches) |

## The US file

nspanel-terminal's US profile assumed the stock runtime enters the terminal at project state 1. On US
panels it is 2, so its `terminal-us.tft` never loaded the receiver. Our build fixes that, and is what
Office, Kitchen, Lounge and Master Bathroom have run since 2026-11-14. It is reproducible byte for byte:

```
git -C nspanel-terminal checkout f0c1394
python3 NSPanelManager-firmware/firmware_espidf/tools/terminal_us_state2.py nspanel-terminal us/gui.tft 98
```

(`clang-21` on PATH.) The script takes `firmware/terminal-us.tft` at that commit, applies the state-2
selector patch (0xC072 = `cmp r0,#2`), rebuilds the loader with `NSPANEL_ENTRY_STATE=2`, and numbers the
native image 98, apart from upstream's versions: the display keeps its installed native code when an
incoming TFT reports the same version.

nspanel-terminal has since made the same fix itself (`45deb5f`, native 95, not yet in a release, and
not yet run on a US panel here). Moving to it is a separate change, tested on a panel first.

## The EU file

Untested here: there is no EU panel in this house. Per nspanel-terminal `45deb5f`, its native code is
byte-identical to the EU 94 image and only the version metadata changed.
