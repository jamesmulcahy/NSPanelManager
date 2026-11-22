"""
LVGL is the only display mode: the Nextion HMI UI was removed (NEXTION_REMOVAL_PLAN.md, M1).

Writes display_mode=lvgl for every panel: creates the row where it is missing, updates it where it says "nextion".
Rows are not deleted, so a rollback to a manager from before this change keeps every panel in LVGL mode instead of
offering the Nextion TFT as a GUI update. The reverse is a no-op: which panels were on Nextion is not kept.
"""

from django.db import migrations


def set_every_panel_to_lvgl(apps, schema_editor):
    NSPanel = apps.get_model("web", "NSPanel")
    NSPanelSettings = apps.get_model("web", "NSPanelSettings")
    for panel in NSPanel.objects.all():
        # Not update_or_create: duplicate rows (no unique constraint is relied on) would raise MultipleObjectsReturned.
        if NSPanelSettings.objects.filter(nspanel=panel, name="display_mode").update(value="lvgl") == 0:
            NSPanelSettings.objects.create(nspanel=panel, name="display_mode", value="lvgl")


class Migration(migrations.Migration):
    dependencies = [
        ("web", "0075_firmwareupload"),
    ]

    operations = [
        migrations.RunPython(set_every_panel_to_lvgl, migrations.RunPython.noop),
    ]
