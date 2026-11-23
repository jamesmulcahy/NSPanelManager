"""
The "US Horizontal (Mirrored)" panel orientation was removed: the firmware has no rotation, so a mirrored panel drew
the landscape layout upside down. Panels that had it become plain horizontal. The reverse is a no-op.
"""

from django.db import migrations


def mirrored_to_horizontal(apps, schema_editor):
    NSPanelSettings = apps.get_model("web", "NSPanelSettings")
    NSPanelSettings.objects.filter(name="us_panel_orientation", value="horizontal_mirrored").update(value="horizontal")


class Migration(migrations.Migration):
    dependencies = [
        ("web", "0076_display_mode_lvgl"),
    ]

    operations = [
        migrations.RunPython(mirrored_to_horizontal, migrations.RunPython.noop),
    ]
