# Seeds the dev stack's database (run with `manage.py shell` by nspm-entrypoint.sh) so
# MQTTManager connects to the stack's own broker and the simulated panels are already
# accepted. It only fills in what is missing, so it is safe to run on every start.
import os

from web.models import NSPanel, Room
from web.settings_helper import does_setting_exist, set_setting_value

settings = {
    "mqtt_server": "mosquitto",
    "mqtt_port": "1883",
    "manager_address": "nspm",
    "manager_port": "8000",
}
for name, value in settings.items():
    if not does_setting_exist(name):
        set_setting_value(name, value)

room = Room.objects.order_by("id").first()
if room is None:
    room = Room.objects.create(friendly_name="Dev Room")

# Must match the MACs and names nspanel_sim.py uses.
for number in range(1, int(os.environ.get("NSPM_DEV_SIM_PANELS", "1")) + 1):
    NSPanel.objects.get_or_create(
        mac_address=f"02:00:00:00:00:{number:02X}",
        defaults={"friendly_name": f"Sim Panel {number}", "model": "sonoff", "room": room, "accepted": True},
    )

print("Dev stack database seeded.")
