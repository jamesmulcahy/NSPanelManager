"""
Which TFT a panel is served, and what a panel's TFT md5 is. See docs/LVGL_PANEL_MODE.md.

LVGL on the nspanel-terminal TFT is the only display mode: the Nextion HMI UI was removed, so every panel is served a
terminal TFT. Migration 0076 rewrote the old "display_mode" rows to "lvgl"; a stale "nextion" row (a rollback to an
older manager can write one) is ignored.

The terminal TFT is chosen by layout. A US panel mounted sideways ("us_panel_orientation" horizontal or
horizontal_mirrored) uses the landscape layout, which is what the EU terminal TFT draws: it gets the EU TFT, and the
firmware is told is_us_panel=false (see lvgl_is_us_layout), as QEMU's "eu-on-us" does.
"""

import hashlib
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage

from .settings_helper import get_nspanel_setting_with_default

DISPLAY_MODE_NEXTION = "nextion"
DISPLAY_MODE_LVGL = "lvgl"
NEXTION_REMOVED_MESSAGE = "LVGL is the only display mode: the Nextion HMI UI was removed, so the Nextion display mode can no longer be chosen."

# Values the firmware takes for {"command": "lvgl_theme"} and {"command": "lvgl_background"}. "light" is left out: the
# firmware takes it as "grey".
LVGL_THEMES = {"auto": "Auto (the background's own)", "dark": "Dark", "grey": "Grey", "ocean": "Ocean", "dusk": "Dusk", "aurora": "Aurora", "peaks": "Peaks", "vesuvius": "Vesuvius", "parthenon": "Parthenon"}
LVGL_BACKGROUNDS = {"none": "None", "ocean": "Ocean", "dusk": "Dusk", "aurora": "Aurora", "peaks": "Peaks", "vesuvius": "Vesuvius", "parthenon": "Parthenon"}

# tft_file_type of each terminal TFT upload -> its path in terminal_storage().
TERMINAL_TFT_PATHS = {"terminal_us": "us/gui.tft", "terminal_eu": "eu/gui.tft"}
# The terminal TFTs the image ships (HMI_files/terminal/README.md), in the default storage. Served
# when nothing was uploaded for that layout, so a new install can put panels in LVGL mode without an upload.
BUNDLED_TERMINAL_TFT_PATHS = {"terminal_us": "HMI_files/terminal/us/gui.tft", "terminal_eu": "HMI_files/terminal/eu/gui.tft"}
TERMINAL_TFT_LABELS = {"terminal_us": "Terminal TFT (US)", "terminal_eu": "Terminal TFT (EU)"}


def terminal_storage():
    return FileSystemStorage(location=settings.TERMINAL_TFT_ROOT)


def get_display_mode(panel_id) -> str:
    """Always "lvgl": a stale "nextion" row is no longer honoured."""
    return DISPLAY_MODE_LVGL


def lvgl_is_us_layout(panel_id) -> bool:
    """
    Whether the panel draws the US (portrait) layout. A US panel mounted sideways (horizontal or horizontal_mirrored)
    draws the landscape layout, as an EU panel does.
    """
    if get_nspanel_setting_with_default(panel_id, "is_us_panel", "False") != "True":
        return False
    return get_nspanel_setting_with_default(panel_id, "us_panel_orientation", "vertical") not in ("horizontal", "horizontal_mirrored")


def terminal_tft_type(panel_id) -> str:
    """The terminal TFT upload type for this panel's layout."""
    return "terminal_us" if lvgl_is_us_layout(panel_id) else "terminal_eu"


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
    """(storage, path) of the terminal TFT this panel should run."""
    return staged_terminal_tft_file(terminal_tft_type(panel_id))


def upload_tft_file(tft_file_type):
    """(storage, path) an upload of this tft_file_type is saved to, or (None, None) for an unknown type."""
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
    "nextion" is only ever an earlier upload of NSPM's Nextion TFT (TftUpload keeps those).
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
    upload = TftUpload.objects.filter(md5=md5).order_by("-uploaded_at", "-id").first()
    if upload is not None:
        return {"kind": upload.kind, "label": f"{tft_type_label(upload.target)}, an older upload", "current": False}
    return {"kind": "unknown", "label": f"Unknown TFT ({md5[:8]})", "current": False}
