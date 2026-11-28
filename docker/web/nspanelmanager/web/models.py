from datetime import datetime
from logging import NullHandler

import django.utils
from django.db import models
from django.db.models import F
from requests.models import default_hooks


class Settings(models.Model):
    name = models.CharField(max_length=255, unique=True)
    value = models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.name


class NSPanelSettings(models.Model):
    nspanel = models.ForeignKey("NSPanel", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    def __str__(self) -> str:
        return f"{self.nspanel.friendly_name}::{self.name}"


class Room(models.Model):
    # Get the next free number in the ordering
    def number():
        no = Room.objects.all().count()
        if no == None:
            return 1
        else:
            return no + 1

    class HomeAssistantLink(models.TextChoices):
        UNSET = "unset"  # Never decided; the Home Assistant room sync asks about it
        LINKED = "linked"  # home_assistant_area_id is set
        NONE = "none"  # The user said "no association"; the room sync skips it

    friendly_name = models.CharField(max_length=30)
    displayOrder = models.IntegerField(default=number)
    room_temp_provider = models.CharField(max_length=255, default="")
    room_temp_sensor = models.CharField(max_length=255, default="")
    home_assistant_link = models.CharField(max_length=8, choices=HomeAssistantLink.choices, default=HomeAssistantLink.UNSET)
    # The HA area_id (not its name, which can be renamed). Empty unless home_assistant_link is "linked".
    home_assistant_area_id = models.CharField(max_length=255, default="", blank=True)

    def __str__(self) -> str:
        return "room_obj: " + str(self.id) + "::" + self.friendly_name

    def first_media_player(self):
        """The room's first media player: entity page order, then slot order; None when it has none.

        Mirrors Room::first_media_player() in the MQTTManager, which the open-media-player buttons and the screensaver's
        now-playing card follow. Scenes pages are not entity pages there, and only slots within the page size count.
        """
        return (
            Entity.objects.filter(
                room=self,
                entity_type=Entity.EntityType.MEDIA_PLAYER,
                entities_page__is_scenes_page=False,
                room_view_position__lt=F("entities_page__page_type"),
            )
            .order_by("entities_page__display_order", "entities_page_id", "room_view_position")
            .first()
        )


class IgnoredHomeAssistantArea(models.Model):
    """A Home Assistant area the user doesn't want to be asked about again when syncing rooms."""

    area_id = models.CharField(max_length=255, unique=True)


class RoomEntitiesPage(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, null=True)
    display_order = models.IntegerField()
    page_type = models.IntegerField()  # Is this page displaying 4, 8 or 12 entities?
    is_scenes_page = models.BooleanField(default=False)


class NSPanel(models.Model):
    class NSPanelModel(models.TextChoices):
        SONOFF = "sonoff"
        CUSTOM = "custom"
        WAVESHARE_P4 = "waveshare_p4"

    mac_address = models.CharField(max_length=17)
    friendly_name = models.CharField(max_length=100)
    version = models.CharField(max_length=15, default="")
    model = models.CharField(max_length=32, choices=NSPanelModel.choices)
    # The features the panel last registered with, a JSON array of strings ("" = none). Written by MQTTManager, so that they
    # are known after a manager restart (panels only send them in a register_request).
    features = models.TextField(default="", blank=True)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    button1_mode = models.IntegerField(default=0)
    button1_detached_mode_entity = models.ForeignKey("Entity", on_delete=models.SET_NULL, blank=True, null=True, related_name="+")
    button2_mode = models.IntegerField(default=0)
    button2_detached_mode_entity = models.ForeignKey("Entity", on_delete=models.SET_NULL, blank=True, null=True, related_name="+")
    md5_firmware = models.CharField(max_length=64, default="")
    md5_data_file = models.CharField(max_length=64, default="")
    md5_tft_file = models.CharField(max_length=64, default="")
    denied = models.BooleanField(default=False)
    accepted = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.friendly_name


def _default_nspanel_status_data():
    pass


class RelayGroup(models.Model):
    friendly_name = models.CharField(max_length=255, default="")
    register_as_light = models.BooleanField(default=False)


class RelayGroupBinding(models.Model):
    relay_group = models.ForeignKey(RelayGroup, on_delete=models.CASCADE, null=True, default=None)
    nspanel = models.ForeignKey(NSPanel, on_delete=models.CASCADE)
    relay_num = models.IntegerField(default=1)


class Entity(models.Model):
    class EntityType(models.TextChoices):
        LIGHT = "light"
        SWITCH = "switch"
        BUTTON = "button"
        THERMOSTAT = "thermostat"
        MEDIA_PLAYER = "media_player"
        COVER = "cover"

    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    friendly_name = models.CharField(max_length=255, default="")
    entities_page = models.ForeignKey(RoomEntitiesPage, on_delete=models.CASCADE, null=True)
    room_view_position = models.IntegerField(default=0)
    entity_type = models.CharField(max_length=64, choices=EntityType)
    entity_data = models.JSONField(default=dict)


class Scene(models.Model):
    friendly_name = models.CharField(max_length=32)
    # The name of the scene in Home Assistant or OpenHAB
    backend_name = models.CharField(max_length=32, null=True, default=None)
    scene_type = models.CharField(max_length=64)
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.CASCADE)
    room_view_position = models.IntegerField()
    entities_page = models.ForeignKey(RoomEntitiesPage, on_delete=models.CASCADE, null=True)


class LightState(models.Model):
    light = models.ForeignKey(Entity, on_delete=models.CASCADE)
    scene = models.ForeignKey(Scene, on_delete=models.CASCADE)
    color_mode = models.CharField(max_length=32, default="dimmer")
    light_level = models.IntegerField(default=0)
    color_temperature = models.IntegerField(default=4000)
    hue = models.IntegerField(default=0)
    saturation = models.IntegerField(default=0)


class Message(models.Model):
    title = models.CharField(max_length=255)
    message = models.TextField()
    read = models.BooleanField(default=False)


class TftUpload(models.Model):
    """A TFT file the manager has been given, kept so that a panel's md5 can be named after the file has been replaced."""

    class Kind(models.TextChoices):
        NEXTION = "nextion"  # NSPM's Nextion TFT, uploaded into a background slot
        TERMINAL = "terminal"  # An nspanel-terminal TFT, for panels in LVGL mode

    md5 = models.CharField(max_length=32, db_index=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    target = models.CharField(max_length=64)  # The upload's tft_file_type, ex. "us4" or "terminal_us"
    uploaded_at = models.DateTimeField(auto_now_add=True)


class FirmwareUpload(models.Model):
    """A firmware image the manager has staged, kept so that a panel's md5 can be named after the file has been replaced."""

    class Source(models.TextChoices):
        UPLOAD = "upload"  # Uploaded by hand
        GITHUB = "github"  # Staged from a GitHub release
        BUNDLED = "bundled"  # Shipped in the manager image

    md5 = models.CharField(max_length=32, db_index=True)
    model = models.CharField(max_length=16)  # A model id from board_models.MODELS
    source = models.CharField(max_length=16, choices=Source.choices)
    repo = models.CharField(max_length=200, blank=True, default="")
    tag = models.CharField(max_length=100, blank=True, default="")
    commit = models.CharField(max_length=40, blank=True, default="")
    run_url = models.CharField(max_length=500, blank=True, default="")
    staged_at = models.DateTimeField(auto_now_add=True)
