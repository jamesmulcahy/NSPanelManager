"""
/rest/v2/nspanels/<id>/settings: a panel's settings (web.models.NSPanelSettings), typed.

Deliberately tight for now: only the LVGL panel mode settings (docs/LVGL_PANEL_MODE.md), so the new
display mode and look can be driven without replaying the whole panel settings form. The other panel
settings come later, with the panel page's move to React (HAPanel.md, "REST v2 panel settings").

Storage is unchanged: one NSPanelSettings row per name, as the panel settings form writes them and
MQTTManager reads them (NSPanel::_get_nspanel_setting_with_default).

  * display_mode: "nextion" (also what an absent row means) or "lvgl".
  * lvgl_theme / lvgl_background: a name, or null for "keep the panel's own": no row, so the manager never
    sends that part of the look. The form's empty choice means the same.

PATCH writes only what changes, and reloads MQTTManager only then, so sending back what GET returned
changes nothing.
"""

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response

from web import display_mode as modes
from web.models import NSPanel, NSPanelSettings
from web.apps import send_mqttmanager_reload_command

from .rooms import JsonErrorAPIView
from .schema import extend_schema

logger = logging.getLogger(__name__)


class StrictChoiceField(serializers.ChoiceField):
    """Only a JSON string (or null where allowed): DRF's own ChoiceField also takes 1 for "1"."""

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid_choice", input=data)
        return super().to_internal_value(data)


class NSPanelSettingsSerializer(serializers.Serializer):
    """A panel's settings, for reading and (with partial=True) for PATCH."""

    display_mode = StrictChoiceField(
        choices=list(modes.DISPLAY_MODES),
        help_text="Which TFT the manager serves this panel, and so which UI it runs: NSPM's Nextion pages, or LVGL on the terminal TFT.",
    )
    lvgl_theme = StrictChoiceField(
        choices=list(modes.LVGL_THEMES),
        allow_null=True,
        help_text="LVGL palette. null: keep the panel's own (the manager never sends one).",
    )
    lvgl_background = StrictChoiceField(
        choices=list(modes.LVGL_BACKGROUNDS),
        allow_null=True,
        help_text="LVGL page background. null: keep the panel's own (the manager never sends one).",
    )

    def to_internal_value(self, data):
        # Unknown keys are an error rather than ignored, as in the other /rest/v2/ views: a client sending
        # one has a bug (or a typo) that a 200 would hide.
        if isinstance(data, dict):
            errors = {key: ["Unknown field."] for key in data if key not in self.fields}
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


def _build_errors_serializer():
    messages = {"__module__": __name__, "__doc__": "A 400 from PATCH: error messages by field name. Maps onto react-hook-form's setError()."}
    for name in [*NSPanelSettingsSerializer().fields, "non_field_errors"]:
        messages[name] = serializers.ListField(child=serializers.CharField(), required=False)
    # Instead of the above, for a body that isn't valid JSON.
    messages["detail"] = serializers.CharField(required=False)
    return type("NSPanelSettingsErrorsSerializer", (serializers.Serializer,), messages)


NSPanelSettingsErrorsSerializer = _build_errors_serializer()


class NSPanelDetailSerializer(serializers.Serializer):
    """The error body for a missing panel, or a request rejected before validation (invalid JSON, a failed CSRF check)."""

    status = serializers.CharField()
    message = serializers.CharField()


NAMES = tuple(NSPanelSettingsSerializer().fields)


def _rows(panel):
    return dict(NSPanelSettings.objects.filter(nspanel=panel, name__in=NAMES).values_list("name", "value"))


def read_settings(panel):
    rows = _rows(panel)
    mode = rows.get("display_mode")
    return {
        "display_mode": mode if mode in modes.DISPLAY_MODES else modes.DISPLAY_MODE_NEXTION,
        # A row with a value the firmware does not draw reads as unmanaged, as the form shows it.
        "lvgl_theme": rows.get("lvgl_theme") if rows.get("lvgl_theme") in modes.LVGL_THEMES else None,
        "lvgl_background": rows.get("lvgl_background") if rows.get("lvgl_background") in modes.LVGL_BACKGROUNDS else None,
    }


def write_settings(panel, validated):
    """Store the validated settings that differ from what is stored. Returns the names written."""
    changed = []
    rows = _rows(panel)
    for name, value in validated.items():
        if value is None:
            if name in rows:
                NSPanelSettings.objects.filter(nspanel=panel, name=name).delete()
                changed.append(name)
        elif rows.get(name) != value:
            NSPanelSettings.objects.update_or_create(nspanel=panel, name=name, defaults={"value": value})
            changed.append(name)
    return changed


class NSPanelSettingsView(JsonErrorAPIView):
    http_method_names = ["get", "patch", "head"]

    @extend_schema(responses={200: NSPanelSettingsSerializer, 404: NSPanelDetailSerializer})
    def get(self, request, pk):
        return Response(NSPanelSettingsSerializer(read_settings(get_object_or_404(NSPanel, pk=pk))).data)

    @extend_schema(
        request=NSPanelSettingsSerializer,
        responses={200: NSPanelSettingsSerializer, 400: NSPanelSettingsErrorsSerializer, 403: NSPanelDetailSerializer, 404: NSPanelDetailSerializer, 415: NSPanelDetailSerializer},
    )
    def patch(self, request, pk):
        with transaction.atomic():
            panel = get_object_or_404(NSPanel.objects.select_for_update(), pk=pk)
            serializer = NSPanelSettingsSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            changed = write_settings(panel, serializer.validated_data)
        if changed:
            logger.info("NSPanel %s settings changed: %s", panel.id, ", ".join(changed))
            send_mqttmanager_reload_command()
        return Response(NSPanelSettingsSerializer(read_settings(panel)).data)
