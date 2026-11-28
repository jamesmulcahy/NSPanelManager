#!/bin/bash
# Replace the firmware the manager image ships by default (docker/web/nspanelmanager/firmware/)
# with a CI build of the fork's panel firmware, and rewrite firmware/PROVENANCE.md to match.
#
#   docker/fetch_fork_firmware.sh            # latest successful push build of fork
#   docker/fetch_fork_firmware.sh <run id>   # a given "Build firmware" run
#
# Needs gh (logged in) and python3. Nothing is built locally: the images are the artifacts of
# the firmware repo's .github/workflows/build.yml, which builds both boards on every merge into
# fork. For each board it writes:
#   firmware/<model>/firmware.bin      the app image panels download for an OTA update
#   firmware/<model>/merged_flash.bin  bootloader + partition table + app, for a serial flash
# where <model> is sonoff (original_sonoff, ESP32) or waveshare_p4 (custom_pcb, ESP32-P4).
# The firmware has served its web UI from the app image since NSPanelManager-firmware b314a06, so
# builds have no LittleFS image: sonoff/data_file.bin is kept as it is, the last one built, for
# panels still on firmware older than that (newer firmware reports md5_littlefs "embedded" and
# never downloads it). waveshare_p4 has never run such firmware and ships no data_file.bin.
#
# Then run the Django tests (web.tests.test_default_firmware checks the files against
# PROVENANCE.md) and commit the result.
set -euo pipefail

FIRMWARE_REPO="${FIRMWARE_REPO:-jamesmulcahy/NSPanelManager-firmware}"
BRANCH="fork"
DEST="$(cd "$(dirname "$0")/web/nspanelmanager/firmware" && pwd)"

RUN_ID="${1:-}"
if [ -z "${RUN_ID}" ]; then
  RUN_ID="$(gh run list -R "${FIRMWARE_REPO}" --workflow build.yml --branch "${BRANCH}" --event push \
    --status success --limit 1 --json databaseId -q '.[0].databaseId')"
  if [ -z "${RUN_ID}" ]; then
    echo "No successful push build of ${BRANCH} found in ${FIRMWARE_REPO}." >&2
    exit 1
  fi
fi

read -r RUN_SHA RUN_CONCLUSION RUN_URL RUN_DATE < <(gh run view "${RUN_ID}" -R "${FIRMWARE_REPO}" \
  --json headSha,conclusion,url,updatedAt -q '[.headSha, .conclusion, .url, .updatedAt] | @tsv')
if [ "${RUN_CONCLUSION}" != "success" ]; then
  echo "Run ${RUN_ID} concluded '${RUN_CONCLUSION}', not success." >&2
  exit 1
fi
SHORT_SHA="${RUN_SHA:0:8}"

# Is the build the firmware at the branch head? Later commits may only touch CI or docs, which
# build.yml's path filter skips, so compare the firmware sources rather than the commit.
HEAD_SHA="$(gh api "repos/${FIRMWARE_REPO}/branches/${BRANCH}" -q .commit.sha)"
if [ "${HEAD_SHA}" == "${RUN_SHA}" ]; then
  HEAD_NOTE="This is the head of \`${BRANCH}\`."
else
  CHANGED="$(gh api "repos/${FIRMWARE_REPO}/compare/${RUN_SHA}...${HEAD_SHA}" \
    -q '[.files[].filename | select(startswith("firmware_espidf/") or . == ".github/workflows/build.yml")] | length')"
  if [ "${CHANGED}" == "0" ]; then
    HEAD_NOTE="The head of \`${BRANCH}\` was \`${HEAD_SHA:0:8}\`, which changes nothing under \`firmware_espidf/\`, so this is the firmware as of \`${HEAD_SHA:0:8}\` too."
  else
    HEAD_NOTE="The head of \`${BRANCH}\` was \`${HEAD_SHA:0:8}\`, which changes ${CHANGED} firmware file(s) since this build: a newer build may be due."
  fi
fi

# The artifacts are untrusted data: they get their own empty directory and are only read by
# python3 -I, run from outside it.
if [ ! -f "${DEST}/sonoff/data_file.bin" ]; then
  echo "${DEST}/sonoff/data_file.bin is missing; restore it from git before refreshing." >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
mkdir "${WORK}/dl"
gh run download "${RUN_ID}" -R "${FIRMWARE_REPO}" -D "${WORK}/dl"

for pair in sonoff:original_sonoff waveshare_p4:custom_pcb; do
  model="${pair%%:*}"
  env="${pair#*:}"
  src="${WORK}/dl/firmware-${env}-${SHORT_SHA}"
  if [ ! -d "${src}" ]; then
    echo "Run ${RUN_ID} has no artifact firmware-${env}-${SHORT_SHA}." >&2
    exit 1
  fi
  # The bootloader goes at 0x1000 on the ESP32 and at 0x2000 on the ESP32-P4.
  if [ "${model}" == "waveshare_p4" ]; then boot_offset=0x2000; else boot_offset=0x1000; fi
  mkdir -p "${DEST}/${model}"

  # Checks the images against the build's own partition table, then writes the three files.
  cd /
  python3 -I -c '
import struct, sys

src, dest, boot_offset = sys.argv[1], sys.argv[2], int(sys.argv[3], 16)
read = lambda name: open(f"{src}/{name}", "rb").read()
boot, table, app = read("bootloader.bin"), read("partitions.bin"), read("firmware.bin")

parts = {}
for i in range(0, len(table), 32):
    magic, ptype, subtype, offset, size, label = struct.unpack_from("<HBBII16s", table, i)
    if magic != 0x50AA:
        break
    parts[label.split(b"\0")[0].decode()] = (offset, size)
app_offset, app_size = parts["ota_0"]
if len(app) > app_size:
    sys.exit(f"{src}: firmware.bin is {len(app)} B, the app slot holds {app_size} B")
if app[:1] != b"\xe9" or boot[:1] != b"\xe9":
    sys.exit(f"{src}: firmware.bin or bootloader.bin is not an ESP image")

# The spiffs partition is left out: the firmware formats a blank one on first boot.
merged = bytearray(b"\xff" * (app_offset + len(app)))
for offset, data in ((boot_offset, boot), (0x8000, table), (app_offset, app)):
    merged[offset:offset + len(data)] = data
for name, data in (("firmware.bin", app), ("merged_flash.bin", merged)):
    with open(f"{dest}/{name}", "wb") as f:
        f.write(data)
print(f"{dest}: app {len(app)}/{app_size} B")
' "${src}" "${DEST}/${model}" "${boot_offset}"
done

# custom is the retired ESP32-S3 board's slot: nothing builds it any more, and PROVENANCE.md
# below records only sonoff and waveshare_p4.
rm -rf "${DEST}/custom"

shipped() {
  (cd "${DEST}" && ls sonoff/firmware.bin sonoff/data_file.bin sonoff/merged_flash.bin waveshare_p4/firmware.bin waveshare_p4/merged_flash.bin)
}

file_table() {
  for path in $(shipped); do
      model="${path%%/*}"
      name="${path#*/}"
      f="${DEST}/${path}"
      # shellcheck disable=SC2016 # the backticks are Markdown
      printf '| `%s/%s` | %s | `%s` | `%s` |\n' "${model}" "${name}" "$(stat -c %s "${f}")" \
        "$(md5sum "${f}" | cut -d' ' -f1)" "$(sha256sum "${f}" | cut -d' ' -f1)"
  done
}

checksums() {
  # shellcheck disable=SC2046 # the paths have no spaces
  (cd "${DEST}" && "$1" $(shipped))
}

cat >"${DEST}/PROVENANCE.md" <<EOF
# Default panel firmware

These are the images the manager serves before anyone uploads firmware from the UI
(\`download_firmware\`, \`download_data_file\` and their \`checksum_*\` views, and MQTTManager's
\`MqttManagerConfig::update_firmware_checksum\`). An upload overwrites them in the container, so a
new image brings them back.

They are the CI build of the fork's panel firmware:

- Firmware: [${FIRMWARE_REPO}@\`${RUN_SHA}\`](https://github.com/${FIRMWARE_REPO}/commit/${RUN_SHA})
- Built by: [Build firmware run ${RUN_ID}](${RUN_URL}), push to \`${BRANCH}\`, finished ${RUN_DATE}
- ${HEAD_NOTE}
- Fetched: $(date -u +%Y-%m-%dT%H:%M:%SZ)

\`sonoff\` is the \`original_sonoff\` build (ESP32), \`waveshare_p4\` the \`custom_pcb\` build (ESP32-P4).
\`merged_flash.bin\` is made from the same run's bootloader (at 0x1000 on the ESP32, 0x2000 on the
ESP32-P4), partition table (0x8000) and app (ota_0), for \`esptool.py write_flash 0x0 merged_flash.bin\`;
the firmware formats its spiffs partition on first boot.

The firmware has served its web UI from the app image since NSPanelManager-firmware \`b314a06\`, so
builds no longer make a LittleFS image. \`sonoff/data_file.bin\` is the last one built (firmware
\`8b927332\`, run 43774503255), kept for panels still on older firmware: newer firmware reports
\`md5_littlefs\` as \`embedded\` and never downloads it. \`waveshare_p4\` ships no \`data_file.bin\`.

| File | Bytes | MD5 | SHA-256 |
|---|---|---|---|
$(file_table)

## Refresh

\`\`\`sh
docker/fetch_fork_firmware.sh            # latest successful push build of ${BRANCH}
docker/fetch_fork_firmware.sh <run id>   # a given run
\`\`\`

It rewrites the files and this note. \`web.tests.test_default_firmware\` checks the files against
the checksums below, so run the Django tests before committing.

## Checksums

\`md5sum -c\` and \`sha256sum -c\` accept these, run from this directory.

\`\`\`md5
$(checksums md5sum)
\`\`\`

\`\`\`sha256
$(checksums sha256sum)
\`\`\`
EOF

echo "Wrote ${DEST}/PROVENANCE.md (run ${RUN_ID}, ${RUN_SHA})."
