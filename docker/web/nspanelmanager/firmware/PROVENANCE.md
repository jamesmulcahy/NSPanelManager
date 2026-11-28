# Default panel firmware

These are the images the manager serves before anyone uploads firmware from the UI
(`download_firmware`, `download_data_file` and their `checksum_*` views, and MQTTManager's
`MqttManagerConfig::update_firmware_checksum`). An upload overwrites them in the container, so a
new image brings them back.

They are the CI build of the fork's panel firmware:

- Firmware: [jamesmulcahy/NSPanelManager-firmware@`37496de540740a11c1cbff77cdcb6189bbc424f3`](https://github.com/jamesmulcahy/NSPanelManager-firmware/commit/37496de540740a11c1cbff77cdcb6189bbc424f3)
- Built by: [Build firmware run 46160670962](https://github.com/jamesmulcahy/NSPanelManager-firmware/actions/runs/46160670962), push to `fork`, finished 2026-11-28T15:42:26Z
- This is the head of `fork`.
- Fetched: 2026-11-28T15:44:29Z

`sonoff` is the `original_sonoff` build (ESP32), `waveshare_p4` the `custom_pcb` build (ESP32-P4).
`merged_flash.bin` is made from the same run's bootloader (at 0x1000 on the ESP32, 0x2000 on the
ESP32-P4), partition table (0x8000) and app (ota_0), for `esptool.py write_flash 0x0 merged_flash.bin`;
the firmware formats its spiffs partition on first boot.

The firmware has served its web UI from the app image since NSPanelManager-firmware `b314a06`, so
builds no longer make a LittleFS image. `sonoff/data_file.bin` is the last one built (firmware
`8b927332`, run 43774503255), kept for panels still on older firmware: newer firmware reports
`md5_littlefs` as `embedded` and never downloads it. `waveshare_p4` ships no `data_file.bin`.

| File | Bytes | MD5 | SHA-256 |
|---|---|---|---|
| `sonoff/data_file.bin` | 585728 | `e5eb598007754c98d3cce88b20357876` | `773956f950ef26d3687b7bc453cec98227cfd03d161410aa2e19b003702ca8b7` |
| `sonoff/firmware.bin` | 1575968 | `7365d8bdbfdfdbfe2440d1b0212046a8` | `aa47ec8cc039e680d50f78f0cc290e65727f2f5b8d39d1665b84aa63097f6454` |
| `sonoff/merged_flash.bin` | 1641504 | `c1330ab8245da1e93582b490db680e7f` | `fa85fb7d779b59cdc19eb7ff35a739b1946e52316fa5a4cbb202d75ba95f1481` |
| `waveshare_p4/firmware.bin` | 1778832 | `9aca596f4a9265227e349a621f7c01d2` | `350b790a32396f32fca2a5e36c200aba55bbbcc45ef21e6039a1e92ab7a70138` |
| `waveshare_p4/merged_flash.bin` | 1844368 | `0c7e995008148c52d2fcda535b2d7a92` | `61a35a590b75bd96f882cbb016701390d5f146d5e504fd0e86dd2c04beaaf54c` |

## Refresh

```sh
docker/fetch_fork_firmware.sh            # latest successful push build of fork
docker/fetch_fork_firmware.sh <run id>   # a given run
```

It rewrites the files and this note. `web.tests.test_default_firmware` checks the files against
the checksums below, so run the Django tests before committing.

## Checksums

`md5sum -c` and `sha256sum -c` accept these, run from this directory.

```md5
e5eb598007754c98d3cce88b20357876  sonoff/data_file.bin
7365d8bdbfdfdbfe2440d1b0212046a8  sonoff/firmware.bin
c1330ab8245da1e93582b490db680e7f  sonoff/merged_flash.bin
9aca596f4a9265227e349a621f7c01d2  waveshare_p4/firmware.bin
0c7e995008148c52d2fcda535b2d7a92  waveshare_p4/merged_flash.bin
```

```sha256
773956f950ef26d3687b7bc453cec98227cfd03d161410aa2e19b003702ca8b7  sonoff/data_file.bin
aa47ec8cc039e680d50f78f0cc290e65727f2f5b8d39d1665b84aa63097f6454  sonoff/firmware.bin
fa85fb7d779b59cdc19eb7ff35a739b1946e52316fa5a4cbb202d75ba95f1481  sonoff/merged_flash.bin
350b790a32396f32fca2a5e36c200aba55bbbcc45ef21e6039a1e92ab7a70138  waveshare_p4/firmware.bin
61a35a590b75bd96f882cbb016701390d5f146d5e504fd0e86dd2c04beaaf54c  waveshare_p4/merged_flash.bin
```
