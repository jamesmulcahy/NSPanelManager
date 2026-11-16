# Default panel firmware

These are the images the manager serves before anyone uploads firmware from the UI
(`download_firmware`, `download_data_file` and their `checksum_*` views, and MQTTManager's
`MqttManagerConfig::update_firmware_checksum`). An upload overwrites them in the container, so a
new image brings them back.

They are the CI build of the fork's panel firmware:

- Firmware: [jamesmulcahy/NSPanelManager-firmware@`8b9273332076b1b07855cc4fb3bdfaacb57776e0`](https://github.com/jamesmulcahy/NSPanelManager-firmware/commit/8b9273332076b1b07855cc4fb3bdfaacb57776e0)
- Built by: [Build firmware run 43774503255](https://github.com/jamesmulcahy/NSPanelManager-firmware/actions/runs/43774503255), push to `fork`, finished 2026-11-15T23:28:36Z
- The head of `fork` was `824acfaa`, which changes nothing under `firmware_espidf/`, so this is the firmware as of `824acfaa` too.
- Fetched: 2026-11-16T01:05:29Z

`sonoff` is the `original_sonoff` build (ESP32), `custom` the `custom_pcb` build (ESP32-S3).
`data_file.bin` is the build's `littlefs.bin`. `merged_flash.bin` is made from the same run's
bootloader (at 0x1000 on the ESP32, 0x0 on the ESP32-S3), partition table (0x8000), app (ota_0) and
LittleFS image (spiffs partition), for `esptool.py write_flash 0x0 merged_flash.bin`.

| File | Bytes | MD5 | SHA-256 |
|---|---|---|---|
| `sonoff/firmware.bin` | 1621184 | `9b4ed9c32f689fbc9aefafa41ea7e648` | `23d9aa9d7f7250a61f1a4a55fd64ccdcca12adad49f126952c852703db83d9cf` |
| `sonoff/data_file.bin` | 585728 | `e5eb598007754c98d3cce88b20357876` | `773956f950ef26d3687b7bc453cec98227cfd03d161410aa2e19b003702ca8b7` |
| `sonoff/merged_flash.bin` | 4190208 | `6c9017c023a70105b3e255f142f96ed7` | `d0185b77594559ca381cfd82b78818e64bbdbb816490f75c5b9d431e2f21630d` |
| `custom/firmware.bin` | 1555008 | `82c610b69a81f55a14013391d7a6423d` | `3479fe8ba98d962960de36c53b8254f80d7eabbc37aaba9a12719cc77d92be45` |
| `custom/data_file.bin` | 585728 | `3eaf020528db4cfddb90db7e582584fc` | `a906e934b884d20dbb0bc42d58df16eddcd8e028c311db77050c57ce70d3326a` |
| `custom/merged_flash.bin` | 4190208 | `b9878e343d2728713f4cadaafcf8595e` | `be321a8eaf61e7aed8f3ae8881911aefcc356a190827f5cbba99d23153729233` |

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
9b4ed9c32f689fbc9aefafa41ea7e648  sonoff/firmware.bin
6c9017c023a70105b3e255f142f96ed7  sonoff/merged_flash.bin
3eaf020528db4cfddb90db7e582584fc  custom/data_file.bin
82c610b69a81f55a14013391d7a6423d  custom/firmware.bin
b9878e343d2728713f4cadaafcf8595e  custom/merged_flash.bin
```

```sha256
773956f950ef26d3687b7bc453cec98227cfd03d161410aa2e19b003702ca8b7  sonoff/data_file.bin
23d9aa9d7f7250a61f1a4a55fd64ccdcca12adad49f126952c852703db83d9cf  sonoff/firmware.bin
d0185b77594559ca381cfd82b78818e64bbdbb816490f75c5b9d431e2f21630d  sonoff/merged_flash.bin
a906e934b884d20dbb0bc42d58df16eddcd8e028c311db77050c57ce70d3326a  custom/data_file.bin
3479fe8ba98d962960de36c53b8254f80d7eabbc37aaba9a12719cc77d92be45  custom/firmware.bin
be321a8eaf61e7aed8f3ae8881911aefcc356a190827f5cbba99d23153729233  custom/merged_flash.bin
```
