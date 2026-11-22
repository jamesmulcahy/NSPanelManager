"""
Which TFT a panel is served, and what a panel's TFT md5 is. See docs/LVGL_PANEL_MODE.md.

A panel's "display_mode" setting is "lvgl" (the default: an nspanel-terminal TFT; the firmware then draws its pages
with LVGL). The terminal TFT is chosen by layout alone, as the firmware chooses its LVGL layout from is_us_panel alone.
"nextion" (NSPM's Nextion TFT from the background slot in "selected_tft") can no longer be chosen, as the Nextion HMI
UI was removed. Migration 0076 rewrites every panel to "lvgl"; a "nextion" row that turns up later (a rollback to an
older manager can write one) is still honored until the slot code goes.
"""

import hashlib
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage

from .settings_helper import get_nspanel_setting_with_default

DISPLAY_MODE_NEXTION = "nextion"
DISPLAY_MODE_LVGL = "lvgl"
DISPLAY_MODES = {DISPLAY_MODE_NEXTION: "Nextion (NSPM TFT)", DISPLAY_MODE_LVGL: "LVGL (terminal TFT)"}
# What can be chosen (the form, REST v2). A stored "nextion" is only read, never written.
SELECTABLE_DISPLAY_MODES = {DISPLAY_MODE_LVGL: DISPLAY_MODES[DISPLAY_MODE_LVGL]}
NEXTION_REMOVED_MESSAGE = "LVGL is the only display mode: the Nextion HMI UI was removed, so the Nextion display mode can no longer be chosen."

# Values the firmware takes for {"command": "lvgl_theme"} and {"command": "lvgl_background"}. "light" is left out: the
# firmware takes it as "grey".
LVGL_THEMES = {"auto": "Auto (the background's own)", "dark": "Dark", "grey": "Grey", "ocean": "Ocean", "dusk": "Dusk", "aurora": "Aurora", "peaks": "Peaks", "vesuvius": "Vesuvius", "parthenon": "Parthenon"}
LVGL_BACKGROUNDS = {"none": "None", "ocean": "Ocean", "dusk": "Dusk", "aurora": "Aurora", "peaks": "Peaks", "vesuvius": "Vesuvius", "parthenon": "Parthenon"}

SLOTS = ("tft1", "tft2", "tft3", "tft4")
# tft_file_type of each background slot upload -> its path in the default storage.
SLOT_TFT_PATHS = {}
for _slot_number in range(1, 5):
    SLOT_TFT_PATHS[f"eu{_slot_number}"] = f"HMI_files/tft_automation/eu/output_tft{_slot_number}/gui.tft"
    SLOT_TFT_PATHS[f"us{_slot_number}"] = f"HMI_files/tft_automation/us/output_tft{_slot_number}/gui.tft"
    SLOT_TFT_PATHS[f"us{_slot_number}_horizontal_mirrored"] = f"HMI_files/tft_automation/us_horizontal_mirrored/output_tft{_slot_number}/gui.tft"

# tft_file_type of each terminal TFT upload -> its path in terminal_storage().
TERMINAL_TFT_PATHS = {"terminal_us": "us/gui.tft", "terminal_eu": "eu/gui.tft"}
# The terminal TFTs the image ships (HMI_files/terminal/README.md), in the default storage like the slots. Served
# when nothing was uploaded for that layout, so a new install can put panels in LVGL mode without an upload.
BUNDLED_TERMINAL_TFT_PATHS = {"terminal_us": "HMI_files/terminal/us/gui.tft", "terminal_eu": "HMI_files/terminal/eu/gui.tft"}
TERMINAL_TFT_LABELS = {"terminal_us": "Terminal TFT (US)", "terminal_eu": "Terminal TFT (EU)"}


def terminal_storage():
    return FileSystemStorage(location=settings.TERMINAL_TFT_ROOT)


def get_display_mode(panel_id) -> str:
    mode = get_nspanel_setting_with_default(panel_id, "display_mode", DISPLAY_MODE_LVGL)
    return mode if mode in DISPLAY_MODES else DISPLAY_MODE_LVGL


def terminal_tft_type(panel_id) -> str:
    """The terminal TFT upload type for this panel's layout."""
    return "terminal_us" if get_nspanel_setting_with_default(panel_id, "is_us_panel", "False") == "True" else "terminal_eu"


def slot_tft_type(panel_id):
    """The background slot upload type ("eu1", "us4_horizontal_mirrored", ...) this panel uses in Nextion mode, or None."""
    selected_tft = get_nspanel_setting_with_default(panel_id, "selected_tft", "tft1")
    if selected_tft not in SLOTS:
        return None
    slot_number = selected_tft[3:]
    if get_nspanel_setting_with_default(panel_id, "is_us_panel", "False") == "False":
        return f"eu{slot_number}"
    orientation = get_nspanel_setting_with_default(panel_id, "us_panel_orientation", "vertical")
    if orientation == "horizontal":
        # A horizontal US panel with the buttons on the left has the same screen orientation as an EU panel.
        return f"eu{slot_number}"
    if orientation == "horizontal_mirrored":
        return f"us{slot_number}_horizontal_mirrored"
    if orientation == "vertical":
        return f"us{slot_number}"
    return None


def staged_terminal_tft_file(tft_file_type):
    """(storage, path) of the terminal TFT served for this layout: the upload if there is one, else the bundled file."""
    storage, path = terminal_storage(), TERMINAL_TFT_PATHS[tft_file_type]
    if storage.exists(path):
        return storage, path
    return FileSystemStorage(), BUNDLED_TERMINAL_TFT_PATHS[tft_file_type]


def is_bundled_terminal_tft(tft_file_type) -> bool:
    """Whether this layout's terminal TFT is the bundled one (nothing was uploaded)."""
    return not terminal_storage().exists(TERMINAL_TFT_PATHS[tft_file_type])


def panel_tft_file(panel_id):
    """(storage, path) of the TFT this panel should run, or (None, None) when it cannot be worked out."""
    if get_display_mode(panel_id) == DISPLAY_MODE_LVGL:
        return staged_terminal_tft_file(terminal_tft_type(panel_id))
    tft_type = slot_tft_type(panel_id)
    if tft_type is None:
        print(f"ERROR! Could not determine TFT file for NSPanel with ID {panel_id}")
        return None, None
    return FileSystemStorage(), SLOT_TFT_PATHS[tft_type]


def upload_tft_file(tft_file_type):
    """(storage, path) an upload of this tft_file_type is saved to, or (None, None) for an unknown type."""
    if tft_file_type in SLOT_TFT_PATHS:
        return FileSystemStorage(), SLOT_TFT_PATHS[tft_file_type]
    if tft_file_type in TERMINAL_TFT_PATHS:
        return terminal_storage(), TERMINAL_TFT_PATHS[tft_file_type]
    return None, None


# (storage location, path) -> (mtime, size, md5), so that describing a panel does not re-read every staged TFT.
_md5_cache = {}


def file_md5(storage, path):
    if storage is None or not storage.exists(path):
        return None
    full_path = storage.path(path)
    stat = os.stat(full_path)
    key = (str(storage.location), path)
    cached = _md5_cache.get(key)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    md5 = hashlib.md5()
    with storage.open(path) as file:
        for chunk in file.chunks():
            md5.update(chunk)
    _md5_cache[key] = (stat.st_mtime_ns, stat.st_size, md5.hexdigest())
    return md5.hexdigest()


def tft_type_label(tft_file_type) -> str:
    if tft_file_type in TERMINAL_TFT_LABELS:
        return TERMINAL_TFT_LABELS[tft_file_type]
    region, _, orientation = tft_file_type.partition("_")
    label = f"NSPM TFT slot {region[2:]} ({region[:2].upper()}"
    return label + (", landscape mirrored)" if orientation else ")")


def describe_tft_md5(md5):
    """
    What a panel's reported TFT md5 is: {"kind": "terminal" | "nextion" | "unknown", "label": ..., "current": bool}.
    "current" is True when the file is the one staged now, False when it matches an earlier upload only.
    """
    from .models import TftUpload

    if not md5:
        return {"kind": "unknown", "label": "Not reported yet", "current": False}
    for tft_file_type in TERMINAL_TFT_PATHS:
        if file_md5(*staged_terminal_tft_file(tft_file_type)) == md5:
            label = tft_type_label(tft_file_type)
            if is_bundled_terminal_tft(tft_file_type):
                label += ", bundled"
            return {"kind": "terminal", "label": label, "current": True}
    for tft_file_type in SLOT_TFT_PATHS:
        if file_md5(*upload_tft_file(tft_file_type)) == md5:
            return {"kind": "nextion", "label": tft_type_label(tft_file_type), "current": True}
    upload = TftUpload.objects.filter(md5=md5).order_by("-uploaded_at", "-id").first()
    if upload is not None:
        return {"kind": upload.kind, "label": f"{tft_type_label(upload.target)}, an older upload", "current": False}
    return {"kind": "unknown", "label": f"Unknown TFT ({md5[:8]})", "current": False}
