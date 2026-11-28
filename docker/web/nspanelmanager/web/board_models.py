"""
The panel models the manager knows, in one place. A model selects the firmware and data file slot (firmware/<id>/)
and nothing else: what a board has or lacks is a feature the panel reports in its register_request.

Adding a board is one entry in MODELS here, one in NSPANEL_MODELS (docker/MQTTManager/include/nspanel/nspanel_model.hpp)
and one in KNOWN_MODELS (react-components/src/lib/panelModels.ts).
"""

from dataclasses import dataclass
from typing import Optional

ESP_IMAGE_MAGIC = 0xE9

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
    # The size of its ota_0/ota_1 app slots, from the firmware repo's partition table for the board.
    app_slot_bytes: int = 0x1B0000


MODELS = (
    BoardModel("sonoff", "Sonoff original NSPanel", 0x0000, "original_sonoff"),  # partitions.csv
    # The legacy ESP32-S3 custom PCB. No longer built; kept so existing panels and database rows keep working.
    BoardModel("custom", "Legacy custom board (ESP32-S3)", 0x0009),
    BoardModel("waveshare_p4", "Waveshare ESP32-P4 board", 0x0012, "custom_pcb", app_slot_bytes=0x400000),  # partitions_p4.csv
)

MODEL_IDS = tuple(model.id for model in MODELS)
CHIP_IDS = {model.id: model.chip_id for model in MODELS}
APP_SLOT_BYTES = {model.id: model.app_slot_bytes for model in MODELS}
# Manager model -> the board's name in the GitHub release, for the models that are still built.
BOARDS = {model.id: model.release_board for model in MODELS if model.release_board}


def chip_name(chip_id: int) -> str:
    return CHIP_NAMES.get(chip_id, "an unknown chip")


def app_image_error(model: str, header: bytes) -> Optional[str]:
    """Why this app image (its first 16 bytes) cannot go in the model's firmware slot, or None if it can."""
    if len(header) < 16 or header[0] != ESP_IMAGE_MAGIC:
        return "not an ESP app image (the first byte is not 0xE9)"
    chip_id = int.from_bytes(header[12:14], "little")
    expected = CHIP_IDS[model]
    if chip_id != expected:
        return f"the image is for {chip_name(chip_id)} (chip id {chip_id:#06x}), but the {model} slot needs {chip_name(expected)} (chip id {expected:#06x})"
    return None
