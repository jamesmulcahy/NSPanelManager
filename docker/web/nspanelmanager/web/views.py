import hashlib
import logging
import os
import signal
import time

import environ
import psutil
from django.core.files.storage import FileSystemStorage
from django.forms.models import model_to_dict
from django.http import JsonResponse
from django.shortcuts import Http404, HttpResponse, redirect, render
from django.views.decorators.csrf import csrf_exempt
from requests import delete
from requests.sessions import Request

from web.openhab_api import get_all_openhab_items
from web.settings_helper import (
    delete_nspanel_setting,
    get_nspanel_setting_with_default,
    get_setting_with_default,
    set_nspanel_setting_value,
    set_setting_value,
)

from . import board_models, display_mode
from .apps import send_mqttmanager_reload_command, start_mqtt_manager
from .github_firmware import FirmwareError, StageLock
from .models import (
    Entity,
    FirmwareUpload,
    Message,
    NSPanel,
    RelayGroup,
    RelayGroupBinding,
    Room,
    RoomEntitiesPage,
    Scene,
    Settings,
    TftUpload,
)

logger = logging.getLogger(__name__)


def get_file_md5sum(filename):
    fs = FileSystemStorage()
    if fs.exists(filename):
        return hashlib.md5(fs.open(filename).read()).hexdigest()
    else:
        return None


def get_base_data(request):
    """Get data that is used on ALL rendered views."""
    data = {
        "ingress_path": request.headers["X-Ingress-Path"] if "X-Ingress-Path" in request.headers else "",
        "board_models": board_models.MODELS,
        "firmware_boards": [[model.id, model.label] for model in board_models.MODELS if model.release_board],
        "enabled_themes": {
            "default": "Default",
            "light": "Light",
            "dark": "Dark",
            "nspmwip": "NSPanel Manager (dark, WIP)",
            "cupcake": "Cupcake",
            "bumblebee": "Bumblebee",
            "emerald": "Emerald",
            "corporate": "Corporate",
            "synthwave": "Synthwave",
            "retro": "Retro",
            "cyberpunk": "Cyberpunk",
            "valentine": "Valentine",
            "halloween": "Halloween",
            "garden": "Garden",
            "forest": "Forest",
            "aqua": "Aqua",
            "lofi": "Lo-Fi",
            "pastel": "Pastel",
            "fantasy": "Fantasy",
            "wireframe": "Wireframe",
            "black": "Black",
            "luxury": "Luxury",
            "dracula": "Dracula",
            "cmyk": "CMYK",
            "autumn": "Autumn",
            "business": "Business",
            "acid": "Acid",
            "lemonade": "Lemonade",
            "night": "Night",
            "coffee": "Coffee",
            "winter": "Winter",
            "dim": "Dim",
            "nord": "Nord",
            "sunset": "Sunset",
        },
        "theme": get_setting_with_default("theme"),
        "version": "%version%",  # This value get's replaced during build
        "manager_address": get_setting_with_default("manager_address"),
        "has_unread_messages": Message.objects.filter(read=False).exists(),
        "icons": [],
    }

    if data["manager_address"] == "":
        environment = environ.Env()
        data["is_home_assistant_addon"] = "IS_HOME_ASSISTANT_ADDON" in environment and environment("IS_HOME_ASSISTANT_ADDON") == "true"

    return data


def index(request):
    return render(request, "index.html", get_base_data(request))


def rooms(request):
    data = get_base_data(request)
    data["rooms"] = []
    # Build dict of online and accepted NSPanels for each room
    for room in Room.objects.all().order_by("displayOrder"):
        data["rooms"].append(
            {
                "room": room,
                "nspanels": room.nspanel_set.filter(accepted=True, denied=False),
            }
        )

    return render(request, "rooms.html", data)


def edit_room(request, room_id: int):
    room = Room.objects.filter(id=room_id).first()
    data = get_base_data(request)
    data.update(
        {
            "total_num_rooms": Room.objects.count(),
            "room": room,
            "nspanels": room.nspanel_set.filter(accepted=True, denied=False),
            "entity_pages": RoomEntitiesPage.objects.filter(room=room),
        }
    )

    return render(request, "edit_room.html", data)


def save_new_room(request):
    new_room = Room()
    new_room.friendly_name = request.POST["friendly_name"]
    new_room.save()

    # Create RoomEntitiesPage for scenes
    scenes_page = RoomEntitiesPage()
    scenes_page.room = new_room
    scenes_page.page_type = 4
    scenes_page.is_scenes_page = True
    scenes_page.display_order = 0
    scenes_page.save()

    # Create RoomEntitiesPage for entities
    entities_page = RoomEntitiesPage()
    entities_page.room = new_room
    entities_page.page_type = 4
    entities_page.is_scenes_page = False
    entities_page.display_order = 0
    entities_page.save()

    send_mqttmanager_reload_command()
    return redirect("edit_room", room_id=new_room.id)


def update_room_form(request, room_id: int):
    room = Room.objects.filter(id=room_id).first()
    room.friendly_name = request.POST["friendly_name"]
    room.room_temp_provider = request.POST["room_temp_provider"]
    room.room_temp_sensor = request.POST["room_temp_sensor"]
    room.save()
    send_mqttmanager_reload_command()
    return redirect("edit_room", room_id=room_id)


def edit_nspanel(request, panel_id: int):
    if get_setting_with_default("use_fahrenheit") == "True":
        temperature_unit = "°F"
    else:
        temperature_unit = "°C"
    settings = {
        "lock_to_default_room": get_nspanel_setting_with_default(panel_id, "lock_to_default_room", "False"),
        "screen_dim_level": get_nspanel_setting_with_default(panel_id, "screen_dim_level", ""),
        "screensaver_dim_level": get_nspanel_setting_with_default(panel_id, "screensaver_dim_level", ""),
        "is_us_panel": get_nspanel_setting_with_default(panel_id, "is_us_panel", "False"),
        "us_panel_orientation": get_nspanel_setting_with_default(panel_id, "us_panel_orientation", "vertical"),
        "show_screensaver_inside_temperature": get_nspanel_setting_with_default(panel_id, "show_screensaver_inside_temperature", "global"),
        "show_screensaver_outside_temperature": get_nspanel_setting_with_default(panel_id, "show_screensaver_outside_temperature", "global"),
        "screensaver_activation_timeout": get_nspanel_setting_with_default(panel_id, "screensaver_activation_timeout", ""),
        "screensaver_mode": get_nspanel_setting_with_default(panel_id, "screensaver_mode", "global"),
        # A panel's own cards setting wins even when empty (no cards on this panel): "global" means there is no row.
        "screensaver_cards_mode": "global" if get_nspanel_setting_with_default(panel_id, "screensaver_cards", None) is None else "custom",
        "screensaver_cards": get_nspanel_setting_with_default(panel_id, "screensaver_cards", ""),
        "screensaver_base_card_seconds": get_nspanel_setting_with_default(panel_id, "screensaver_base_card_seconds", ""),
        "reverse_relays": get_nspanel_setting_with_default(panel_id, "reverse_relays", "False"),
        "relay1_default_mode": get_nspanel_setting_with_default(panel_id, "relay1_default_mode", "False"),
        "relay1_is_light": get_nspanel_setting_with_default(panel_id, "relay1_is_light", "False"),
        "relay2_default_mode": get_nspanel_setting_with_default(panel_id, "relay2_default_mode", "False"),
        "relay2_is_light": get_nspanel_setting_with_default(panel_id, "relay2_is_light", "False"),
        "temperature_calibration": get_nspanel_setting_with_default(panel_id, "temperature_calibration", 0),
        "button1_custom_mqtt_topic": get_nspanel_setting_with_default(panel_id, "button1_mqtt_topic", ""),
        "button1_custom_mqtt_payload": get_nspanel_setting_with_default(panel_id, "button1_mqtt_payload", ""),
        "button2_custom_mqtt_topic": get_nspanel_setting_with_default(panel_id, "button2_mqtt_topic", ""),
        "button2_custom_mqtt_payload": get_nspanel_setting_with_default(panel_id, "button2_mqtt_payload", ""),
        "button1_relay_lower_temperature": get_nspanel_setting_with_default(panel_id, "button1_relay_lower_temperature", ""),
        "button1_relay_upper_temperature": get_nspanel_setting_with_default(panel_id, "button1_relay_upper_temperature", ""),
        "button2_relay_lower_temperature": get_nspanel_setting_with_default(panel_id, "button2_relay_lower_temperature", ""),
        "button2_relay_upper_temperature": get_nspanel_setting_with_default(panel_id, "button2_relay_upper_temperature", ""),
        "default_page": get_nspanel_setting_with_default(panel_id, "default_page", "0"),
        "lvgl_theme": get_nspanel_setting_with_default(panel_id, "lvgl_theme", ""),
        "lvgl_background": get_nspanel_setting_with_default(panel_id, "lvgl_background", ""),
    }

    nspanel = NSPanel.objects.get(id=panel_id)
    panel_info = {}
    panel_info["data"] = nspanel

    terminal_tft_type = display_mode.terminal_tft_type(panel_id)
    staged_md5 = display_mode.file_md5(*display_mode.staged_terminal_tft_file(terminal_tft_type))
    display_info = {
        "themes": display_mode.LVGL_THEMES,
        "backgrounds": display_mode.LVGL_BACKGROUNDS,
        "running": display_mode.describe_tft_md5(nspanel.md5_tft_file),
        "terminal_tft_label": display_mode.TERMINAL_TFT_LABELS[terminal_tft_type],
        "terminal_tft_staged": staged_md5 is not None,
        # The layout (and so the staged terminal TFT) follows the orientation at once, the display image only after a GUI update.
        "us_layout": display_mode.lvgl_is_us_layout(panel_id),
        "image_differs_from_layout": bool(staged_md5 and nspanel.md5_tft_file and nspanel.md5_tft_file != staged_md5),
    }

    data = get_base_data(request)
    data = data | {
        "panel_info": panel_info,
        "display_info": display_info,
        "rooms": Room.objects.all(),
        "settings": settings,
        "temperature_unit": temperature_unit,
        "multiple": [1, 2, 3, 4],
        "max_live_log_messages": get_setting_with_default("max_live_log_messages"),
        "screensaver_mode_global": get_setting_with_default("screensaver_mode"),
        "screensaver_cards_global": get_setting_with_default("screensaver_cards"),
        "now_playing_player": nspanel.room.first_media_player(),
        "now_playing_in_use": "now_playing" in (settings["screensaver_cards"] if settings["screensaver_cards_mode"] == "custom" else (get_setting_with_default("screensaver_cards") or "")),
        "screensaver_base_card_seconds_global": get_setting_with_default("screensaver_base_card_seconds"),
    }

    return render(request, "edit_nspanel.html", data)


def save_panel_settings(request, panel_id: int):
    panel = NSPanel.objects.get(id=panel_id)
    panel.room = Room.objects.get(id=request.POST["room_id"])
    panel.friendly_name = request.POST["name"]
    panel.button1_mode = request.POST["button1_mode"]
    if request.POST["button1_mode"] == "1":  # Detached mode
        # With no entities to choose from the field is empty or missing; the button is then detached without an entity, as when its entity is deleted.
        button1_entity_id = request.POST.get("button1_detached_mode_light", "")
        panel.button1_detached_mode_entity = Entity.objects.get(id=button1_entity_id) if button1_entity_id else None
    else:
        panel.button1_detached_mode_entity = None

    if request.POST["button1_mode"] == "2":  # Custom MQTT Mode
        set_nspanel_setting_value(panel_id, "button1_mqtt_topic", request.POST["button1_custom_mqtt_topic"])
        set_nspanel_setting_value(
            panel_id,
            "button1_mqtt_payload",
            request.POST["button1_custom_mqtt_payload"],
        )
    else:
        delete_nspanel_setting(panel_id, "button1_mqtt_topic")
        delete_nspanel_setting(panel_id, "button1_mqtt_payload")

    panel.button2_mode = request.POST["button2_mode"]
    if request.POST["button2_mode"] == "1":  # Detached mode
        # With no entities to choose from the field is empty or missing; the button is then detached without an entity, as when its entity is deleted.
        button2_entity_id = request.POST.get("button2_detached_mode_light", "")
        panel.button2_detached_mode_entity = Entity.objects.get(id=button2_entity_id) if button2_entity_id else None
    else:
        panel.button2_detached_mode_entity = None

    if request.POST["button2_mode"] == "2":  # Custom MQTT Mode
        set_nspanel_setting_value(panel_id, "button2_mqtt_topic", request.POST["button2_custom_mqtt_topic"])
        set_nspanel_setting_value(
            panel_id,
            "button2_mqtt_payload",
            request.POST["button2_custom_mqtt_payload"],
        )
    else:
        delete_nspanel_setting(panel_id, "button2_mqtt_topic")
        delete_nspanel_setting(panel_id, "button2_mqtt_payload")

    if request.POST["screen_dim_level"].strip():
        set_nspanel_setting_value(panel_id, "screen_dim_level", request.POST["screen_dim_level"])
    else:
        delete_nspanel_setting(panel_id, "screen_dim_level")

    if request.POST["screensaver_dim_level"].strip():
        set_nspanel_setting_value(panel_id, "screensaver_dim_level", request.POST["screensaver_dim_level"])
    else:
        delete_nspanel_setting(panel_id, "screensaver_dim_level")

    if request.POST["screensaver_activation_timeout"].strip():
        set_nspanel_setting_value(
            panel_id,
            "screensaver_activation_timeout",
            request.POST["screensaver_activation_timeout"],
        )
    else:
        delete_nspanel_setting(panel_id, "screensaver_activation_timeout")

    if request.POST["screensaver_mode"] == "global":
        delete_nspanel_setting(panel_id, "screensaver_mode")
    else:
        set_nspanel_setting_value(panel_id, "screensaver_mode", request.POST["screensaver_mode"])

    if request.POST.get("screensaver_cards_mode", "global") == "global":
        delete_nspanel_setting(panel_id, "screensaver_cards")
    else:
        # An empty value is kept: it means no cards on this panel, whatever the global setting is.
        set_nspanel_setting_value(panel_id, "screensaver_cards", request.POST.get("screensaver_cards", "").strip())

    if request.POST.get("screensaver_base_card_seconds", "").strip():
        set_nspanel_setting_value(panel_id, "screensaver_base_card_seconds", request.POST["screensaver_base_card_seconds"].strip())
    else:
        delete_nspanel_setting(panel_id, "screensaver_base_card_seconds")

    if request.POST["show_screensaver_inside_temperature"] == "global":
        delete_nspanel_setting(panel_id, "show_screensaver_inside_temperature")
    else:
        set_nspanel_setting_value(
            panel_id,
            "show_screensaver_inside_temperature",
            request.POST["show_screensaver_inside_temperature"],
        )

    if request.POST["show_screensaver_outside_temperature"] == "global":
        delete_nspanel_setting(panel_id, "show_screensaver_outside_temperature")
    else:
        set_nspanel_setting_value(
            panel_id,
            "show_screensaver_outside_temperature",
            request.POST["show_screensaver_outside_temperature"],
        )

    if request.POST["temperature_calibration"] == "":
        set_nspanel_setting_value(panel_id, "temperature_calibration", float(0))
    else:
        set_nspanel_setting_value(
            panel_id,
            "temperature_calibration",
            float(request.POST.get("temperature_calibration", 0)),
        )

    set_nspanel_setting_value(panel_id, "relay1_default_mode", request.POST["relay1_default_mode"])
    set_nspanel_setting_value(panel_id, "relay2_default_mode", request.POST["relay2_default_mode"])
    set_nspanel_setting_value(panel_id, "default_page", request.POST["default_page"])
    set_nspanel_setting_value(panel_id, "lock_to_default_room", request.POST["lock_to_default_room"])
    set_nspanel_setting_value(panel_id, "reverse_relays", request.POST["reverse_relays"])

    if request.POST["button1_relay_lower_temperature"].strip():
        set_nspanel_setting_value(
            panel_id,
            "button1_relay_lower_temperature",
            request.POST["button1_relay_lower_temperature"],
        )

    if request.POST["button1_relay_upper_temperature"].strip():
        set_nspanel_setting_value(
            panel_id,
            "button1_relay_upper_temperature",
            request.POST["button1_relay_upper_temperature"],
        )

    if request.POST["button2_relay_lower_temperature"].strip():
        set_nspanel_setting_value(
            panel_id,
            "button2_relay_lower_temperature",
            request.POST["button2_relay_lower_temperature"],
        )

    if request.POST["button2_relay_upper_temperature"].strip():
        set_nspanel_setting_value(
            panel_id,
            "button2_relay_upper_temperature",
            request.POST["button2_relay_upper_temperature"],
        )

    if request.POST["panel_type"] == "eu":
        set_nspanel_setting_value(panel_id, "is_us_panel", "False")
    else:
        if request.POST["panel_type"] == "us_horizontal":
            set_nspanel_setting_value(panel_id, "is_us_panel", "True")
            set_nspanel_setting_value(panel_id, "us_panel_orientation", "horizontal")
        elif request.POST["panel_type"] == "us_vertical":
            set_nspanel_setting_value(panel_id, "is_us_panel", "True")
            set_nspanel_setting_value(panel_id, "us_panel_orientation", "vertical")

    save_display_settings(panel_id, request.POST)

    set_nspanel_setting_value(panel_id, "relay1_is_light", request.POST["relay1_is_light"])
    set_nspanel_setting_value(panel_id, "relay2_is_light", request.POST["relay2_is_light"])

    panel.save()
    send_mqttmanager_reload_command()
    return redirect("edit_nspanel", panel_id)


def save_display_settings(panel_id, post):
    """The Display card. A field that is not in the form is left as it is, so older clients keep working."""
    # An empty theme or background means "keep the panel's own": the manager stops sending it.
    for name, choices in (("lvgl_theme", display_mode.LVGL_THEMES), ("lvgl_background", display_mode.LVGL_BACKGROUNDS)):
        if name not in post:
            continue
        if post[name] == "":
            delete_nspanel_setting(panel_id, name)
        elif post[name] in choices:
            set_nspanel_setting_value(panel_id, name, post[name])


def settings_page(request):
    # The page is the React SettingsPage, which loads and saves through /rest/v2/settings.
    return render(request, "settings.html", get_base_data(request))


def home_assistant_sync_page(request):
    # The page is the React HomeAssistantSyncPage, which loads and saves through /rest/v2/home_assistant/*.
    return render(request, "home_assistant_sync.html", get_base_data(request))


@csrf_exempt
def save_new_firmware(request):
    if request.method == "POST":
        if "model" not in request.POST:
            print("Missing 'model' parameter")
            return redirect("/")
        model = request.POST["model"]
        if model not in board_models.MODEL_IDS:
            return HttpResponse("ERROR! Unknown model!", status=400)

        fs = FileSystemStorage()
        uploaded_file = request.FILES["firmware"]
        # The slot decides which chip the image must be for: a mismatch would be flashed over the air and brick the panel.
        error = board_models.app_image_error(model, uploaded_file.read(16))
        uploaded_file.seek(0)
        if error:
            return HttpResponse(f"ERROR! Refusing firmware for the {model} slot: {error}.", status=400, content_type="text/plain")
        try:
            # Not while a stage from GitHub is replacing the same files.
            with StageLock(time.monotonic() + 10):
                # Delete old firmware file:
                fs.delete(f"firmware/{model}/firmware.bin")
                fs.save(f"firmware/{model}/firmware.bin", uploaded_file)
                # Remembered so that a panel still running this file can be named after the file is replaced.
                FirmwareUpload.objects.create(
                    md5=get_file_md5sum(f"firmware/{model}/firmware.bin"),
                    model=model,
                    source=FirmwareUpload.Source.UPLOAD,
                )
        except FirmwareError:
            logger.warning("Firmware upload dropped: a stage from GitHub held the firmware lock for 10 s")
            return redirect("/")
        send_mqttmanager_reload_command()
    return redirect("/")


# TODO: Make exempt only when Debug = true
@csrf_exempt
def save_new_data_file(request):
    if request.method == "POST":
        if "model" not in request.POST:
            print("Missing 'model' parameter")
            return redirect("/")
        if request.POST["model"] not in board_models.MODEL_IDS:
            return HttpResponse("ERROR! Unknown model!", status=400)

        fs = FileSystemStorage()
        # Delete old firmware file:
        fs.delete(f"firmware/{request.POST['model']}/data_file.bin")

        uploaded_file = request.FILES["data_file"]
        fs.save(f"firmware/{request.POST['model']}/data_file.bin", uploaded_file)
        send_mqttmanager_reload_command()
    return redirect("/")


@csrf_exempt
def save_new_merged_flash(request):
    if request.method == "POST":
        if "model" not in request.POST:
            print("Missing 'model' parameter")
            return redirect("/")
        if request.POST["model"] not in board_models.MODEL_IDS:
            return HttpResponse("ERROR! Unknown model!", status=400)

        fs = FileSystemStorage()
        # Delete old firmware file:
        fs.delete(f"firmware/{request.POST['model']}/merged_flash.bin")

        uploaded_file = request.FILES["bin"]
        fs.save(f"firmware/{request.POST['model']}/merged_flash.bin", uploaded_file)
        # send_mqttmanager_reload_command() # Manager does not keep track of checksum for merged_flash.bin. Do not send reload command.
    return redirect("/")


# TODO: Make exempt only when Debug = true


@csrf_exempt
def save_new_tft_file(request):
    if request.method == "POST":
        tft_file_type = request.POST["tft_file_type"]
        fs, file_path = display_mode.upload_tft_file(tft_file_type)
        if fs is None:
            print("ERROR! Unknown TFT file type!")
            return HttpResponse("ERROR! Unknown TFT file type!", status=400)

        print("Saving new TFT file ", file_path)

        uploaded_file = request.FILES["tft_file"]
        fs.delete(file_path)
        fs.save(file_path, uploaded_file)
        # Remembered so that a panel still running this file can be named after it is overwritten.
        TftUpload.objects.create(
            md5=display_mode.file_md5(fs, file_path),
            kind=TftUpload.Kind.TERMINAL,
            target=tft_file_type,
        )
        send_mqttmanager_reload_command()
    return redirect("/")


def download_firmware(request):
    if "model" in request.GET:
        model = request.GET["model"]
        if model not in board_models.MODEL_IDS:
            return HttpResponse("ERROR! Unknown model!", status=400)
    else:
        # As model was not specified, default to sonoff as that was the original model
        model = "sonoff"

    fs = FileSystemStorage()
    if "Range" in request.headers and request.headers["Range"].startswith("bytes="):
        data = fs.open(f"firmware/{model}/firmware.bin").read()
        parts = request.headers["Range"][6:].split("-")
        print(f"Received request for partial firmware download. Parts: {parts}")

        if parts[1] == "":
            range_start = int(parts[0])
            return HttpResponse(data[range_start:], content_type="application/octet-stream")
        else:
            range_start = int(parts[0])
            range_end = int(parts[1])
            return HttpResponse(data[range_start:range_end], content_type="application/octet-stream")

    else:
        return HttpResponse(
            fs.open(f"firmware/{model}/firmware.bin").read(),
            content_type="application/octet-stream",
        )


def download_data_file(request):
    if "model" in request.GET:
        model = request.GET["model"]
        if model not in board_models.MODEL_IDS:
            return HttpResponse("ERROR! Unknown model!", status=400)
    else:
        # As model was not specified, default to sonoff as that was the original model
        model = "sonoff"

    fs = FileSystemStorage()
    if "Range" in request.headers and request.headers["Range"].startswith("bytes="):
        parts = request.headers["Range"][6:].split("-")
        range_start = int(parts[0])
        range_end = int(parts[1])
        print(f"Received request for partial LittleFS download. Start: {range_start}, end: {range_end}")
        data = fs.open(f"firmware/{model}/data_file.bin").read()
        return HttpResponse(data[range_start:range_end], content_type="application/octet-stream")
    else:
        return HttpResponse(
            fs.open(f"firmware/{model}/data_file.bin").read(),
            content_type="application/octet-stream",
        )


def download_tft(request, panel_id):
    # The terminal TFT for the panel's layout (web/display_mode.py).
    fs, tft_file = display_mode.panel_tft_file(panel_id)
    if fs is None or not fs.exists(tft_file):
        # Ex. before a terminal TFT for its layout has been uploaded.
        return HttpResponse("", status=404)

    if "Range" in request.headers and request.headers["Range"].startswith("bytes="):
        parts = request.headers["Range"][6:].split("-")
        range_start = int(parts[0])
        range_end = int(parts[1])
        print(f"Received request for partial EU TFT download. Start: {range_start}, end: {range_end}")
        data = fs.open(tft_file).read()
        return HttpResponse(data[range_start:range_end], content_type="application/octet-stream")
    else:
        return HttpResponse(fs.open(tft_file).read(), content_type="application/octet-stream")


def checksum_response(md5sum):
    # A panel compares the body against its stored checksum, so never send "None" as if it were one.
    if md5sum is None:
        return HttpResponse("", status=404)
    return HttpResponse(md5sum)


def checksum_firmware(request):
    if "model" in request.GET:
        model = request.GET["model"]
        if model not in board_models.MODEL_IDS:
            return HttpResponse("ERROR! Unknown model!", status=400)
    else:
        # As model was not specified, default to sonoff as that was the original model
        model = "sonoff"

    return checksum_response(get_file_md5sum(f"firmware/{model}/firmware.bin"))


def firmware_info(request):
    """What the staged firmware.bin of a model is: its md5, size and build identity (version, image sha-256, ...).
    checksum_firmware keeps answering with the md5 alone, which panels parse. Fields of an image that is not an ESP app
    image are null."""
    model = request.GET.get("model", "sonoff")
    if model not in board_models.MODEL_IDS:
        return HttpResponse("ERROR! Unknown model!", status=400)
    fs = FileSystemStorage()
    name = f"firmware/{model}/firmware.bin"
    if not fs.exists(name):
        return JsonResponse({"error": "No firmware is staged for this model."}, status=404)
    info = board_models.read_app_image_info(fs.path(name))
    return JsonResponse({"model": model, "md5": get_file_md5sum(name), "size": fs.size(name), "build": info.as_dict() if info else None})


def checksum_data_file(request):
    if "model" in request.GET:
        model = request.GET["model"]
        if model not in board_models.MODEL_IDS:
            return HttpResponse("ERROR! Unknown model!", status=400)
    else:
        # As model was not specified, default to sonoff as that was the original model
        model = "sonoff"

    return checksum_response(get_file_md5sum(f"firmware/{model}/data_file.bin"))


def checksum_tft_file(request, panel_id):
    return checksum_response(display_mode.file_md5(*display_mode.panel_tft_file(panel_id)))


def get_manual(request):
    fs = FileSystemStorage()
    response = HttpResponse(fs.open("manual.pdf").read(), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="manual.pdf"'
    return response


def global_scenes(request):
    data = get_base_data(request)
    data["global_scenes"] = Scene.objects.filter(room__isnull=True)
    return render(request, "global_scenes.html", data)


def relay_groups(request):
    data = get_base_data(request)
    data["nspanels"] = NSPanel.objects.all()
    data["relay_groups"] = RelayGroup.objects.all()
    return render(request, "relay_groups.html", data)


def create_or_update_relay_group(request):
    if request.POST["relay_group_id"]:
        new_rg = RelayGroup.objects.get(id=request.POST["relay_group_id"])
    else:
        new_rg = RelayGroup()
    new_rg.friendly_name = request.POST["relay_group_name"]
    new_rg.save()
    send_mqttmanager_reload_command()
    return redirect("relay_groups")


def delete_relay_group(request, relay_group_id):
    rg = RelayGroup.objects.get(id=relay_group_id)
    if rg:
        rg.delete()
    send_mqttmanager_reload_command()
    return redirect("relay_groups")


def add_nspanel_relay_to_group(request):
    rg = RelayGroup.objects.get(id=request.POST["relay_group_id"])
    nspanel = NSPanel.objects.get(id=request.POST["nspanel_id"])
    relay_num = request.POST["relay_num"]

    exists = RelayGroupBinding.objects.filter(nspanel=nspanel, relay_num=relay_num, relay_group=rg).count() > 0
    if not exists:
        binding = RelayGroupBinding()
        binding.relay_group = rg
        binding.nspanel = nspanel
        binding.relay_num = relay_num
        binding.save()
        send_mqttmanager_reload_command()
    return redirect("relay_groups")


def delete_relay_group_binding(request, relay_binding_id):
    binding = RelayGroupBinding.objects.get(id=relay_binding_id)
    if binding:
        binding.delete()
    send_mqttmanager_reload_command()
    return redirect("relay_groups")


def weather_and_time(request):
    if request.method == "POST":
        set_setting_value("location_latitude", request.POST["location_latitude"])
        set_setting_value("location_longitude", request.POST["location_longitude"])
        set_setting_value("weather_wind_speed_format", request.POST["wind_speed_format"])
        set_setting_value("weather_precipitation_format", request.POST["precipitation_format"])
        set_setting_value("outside_temp_sensor_provider", request.POST["outside_temp_provider"])
        set_setting_value("outside_temp_sensor_entity_id", request.POST["outside_temp_sensor"])
        set_setting_value("weather_update_interval", request.POST["weather_update_interval"])
        set_setting_value("date_format", request.POST["date_format"])
        set_setting_value("clock_us_style", request.POST["clock_us_style"])
        set_setting_value("use_fahrenheit", request.POST["use_fahrenheit"])
        send_mqttmanager_reload_command()
        return redirect("weather_and_time")
    else:
        data = get_base_data(request)
        data = data | {
            "date_format": get_setting_with_default("date_format"),
            "clock_us_style": get_setting_with_default("clock_us_style"),
            "use_fahrenheit": get_setting_with_default("use_fahrenheit"),
            "outside_temp_provider": get_setting_with_default("outside_temp_sensor_provider"),
            "outside_temp_sensor": get_setting_with_default("outside_temp_sensor_entity_id"),
            "location_latitude": get_setting_with_default("location_latitude"),
            "location_longitude": get_setting_with_default("location_longitude"),
            "wind_speed_format": get_setting_with_default("weather_wind_speed_format"),
            "precipitation_format": get_setting_with_default("weather_precipitation_format"),
            "weather_update_interval": get_setting_with_default("weather_update_interval"),
        }

        return render(request, "weather_and_time.html", data)


def denied_nspanels(request):
    data = get_base_data(request)
    data["nspanels"] = NSPanel.objects.all()
    return render(request, "denied_nspanels.html", data)


def unblock_nspanel(request, nspanel_id):
    panel = NSPanel.objects.filter(id=nspanel_id).first()
    if panel:
        panel.delete()
        send_mqttmanager_reload_command()
    return redirect("denied_nspanels")


def download_mqttmanager_log(request):
    if os.path.exists("/dev/shm/mqttmanager.log"):
        with open("/dev/shm/mqttmanager.log", "rb") as fh:
            response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
            response["Content-Disposition"] = "inline; filename=" + os.path.basename("mqttmanager_log.txt")
            return response
    raise Http404
