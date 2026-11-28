"""
The panel models the manager knows, in one place. A model selects the firmware and data file slot (firmware/<id>/)
and nothing else: what a board has or lacks is a feature the panel reports in its register_request.

Adding a board is one entry in MODELS here, one in NSPANEL_MODELS (docker/MQTTManager/include/nspanel/nspanel_model.hpp)
and one in KNOWN_MODELS (react-components/src/lib/panelModels.ts).
"""

from dataclasses import dataclass
from typing import Optional

ESP_IMAGE_MAGIC = 0xE9

# esp_app_desc_t sits at offset 32 of an app image: the 24-byte image header plus the 8-byte header of the first segment.
APP_DESC_OFFSET = 32
APP_DESC_MAGIC = 0xABCD5432
APP_DESC_SIZE = 256
SHA256_SIZE = 32
# What parse_app_image needs: the header and esp_app_desc_t, and the trailing SHA-256.
APP_IMAGE_HEAD_SIZE = APP_DESC_OFFSET + APP_DESC_SIZE

# esp_chip_id_t, as found in bytes 12-13 (little-endian) of an app image's header.
CHIP_NAMES = {
    0x0000: "ESP32",
    0x0002: "ESP32-S2",
    0x0005: "ESP32-C3",
    0x0009: "ESP32-S3",
    0x000C: "ESP32-C2",
    0x000D: "ESP32-C6",
    0x0010: "ESP32-H2",
    0x0012: "ESP32-P4",
    0x0017: "ESP32-C5",
}


@dataclass(frozen=True)
class BoardModel:
    id: str
    label: str
    chip_id: int
    # The board's name in the firmware repo's GitHub release (firmware-<board>.bin), or None if it is not built any more.
    release_board: Optional[str] = None


MODELS = (
    BoardModel("sonoff", "Sonoff original NSPanel", 0x0000, "original_sonoff"),
    # The legacy ESP32-S3 custom PCB. No longer built; kept so existing panels and database rows keep working.
    BoardModel("custom", "Legacy custom board (ESP32-S3)", 0x0009),
    BoardModel("waveshare_p4", "Waveshare ESP32-P4 board", 0x0012, "custom_pcb"),
)

MODEL_IDS = tuple(model.id for model in MODELS)
CHIP_IDS = {model.id: model.chip_id for model in MODELS}
# Manager model -> the board's name in the GitHub release, for the models that are still built.
BOARDS = {model.id: model.release_board for model in MODELS if model.release_board}


def chip_name(chip_id: int) -> str:
    return CHIP_NAMES.get(chip_id, "an unknown chip")


def image_chip_id(header: bytes) -> Optional[int]:
    """The chip id (esp_chip_id_t) in an app image's header (its first 16 bytes), or None if it is not an app image."""
    if len(header) < 16 or header[0] != ESP_IMAGE_MAGIC:
        return None
    return int.from_bytes(header[12:14], "little")


def app_image_error(model: str, header: bytes) -> Optional[str]:
    """Why this app image (its first 16 bytes) cannot go in the model's firmware slot, or None if it can."""
    chip_id = image_chip_id(header)
    if chip_id is None:
        return "not an ESP app image (the first byte is not 0xE9)"
    expected = CHIP_IDS[model]
    if chip_id != expected:
        return f"the image is for {chip_name(chip_id)} (chip id {chip_id:#06x}), but the {model} slot needs {chip_name(expected)} (chip id {expected:#06x})"
    return None


@dataclass(frozen=True)
class AppImageInfo:
    """Which build an app image is. The panel reports the same fields (build info in register_request and the status report)."""

    version: str
    project: str
    build_date: str
    idf_version: str
    elf_sha256: str
    # The image's appended SHA-256 (hex), or "" when the image has none (header byte 23, hash_appended, is 0).
    image_sha256: str
    chip: str

    def as_dict(self):
        return {
            "version": self.version,
            "project": self.project,
            "build_date": self.build_date,
            "idf_version": self.idf_version,
            "elf_sha256": self.elf_sha256,
            "image_sha256": self.image_sha256,
            "chip": self.chip,
        }


def _c_string(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8", "replace")


def parse_app_image(head: bytes, tail: bytes) -> Optional[AppImageInfo]:
    """The identity of an app image: head is its first APP_IMAGE_HEAD_SIZE bytes (or more), tail its last 32. None if
    this is not an app image with an esp_app_desc_t."""
    chip_id = image_chip_id(head)
    if chip_id is None or len(head) < APP_IMAGE_HEAD_SIZE:
        return None
    desc = head[APP_DESC_OFFSET : APP_DESC_OFFSET + APP_DESC_SIZE]
    if int.from_bytes(desc[0:4], "little") != APP_DESC_MAGIC:
        return None
    hash_appended = head[23] != 0
    chips = {0x0000: "esp32", 0x0009: "esp32s3", 0x0012: "esp32p4"}
    return AppImageInfo(
        version=_c_string(desc[16:48]),
        project=_c_string(desc[48:80]),
        # esp_app_desc_t: time[16] at +80, date[16] at +96, idf_ver[32] at +112.
        build_date=f"{_c_string(desc[96:112])} {_c_string(desc[80:96])}",
        idf_version=_c_string(desc[112:144]),
        elf_sha256=desc[144:176].hex(),
        image_sha256=tail.hex() if hash_appended and len(tail) == SHA256_SIZE else "",
        chip=chips.get(chip_id, ""),
    )


def read_app_image_info(path) -> Optional[AppImageInfo]:
    """parse_app_image of the file at path, or None if it is missing or not an app image."""
    try:
        with open(path, "rb") as image:
            head = image.read(APP_IMAGE_HEAD_SIZE)
            size = image.seek(0, 2)
            if size < APP_IMAGE_HEAD_SIZE + SHA256_SIZE:
                return None
            image.seek(size - SHA256_SIZE)
            tail = image.read(SHA256_SIZE)
    except OSError:
        return None
    return parse_app_image(head, tail)
