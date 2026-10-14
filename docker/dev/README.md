# NSPanelManager dev stack

A self-contained stack for working on NSPanelManager without a spare panel, a separate
manager or a copy of a production database:

| Service | What it is |
|---|---|
| `mosquitto` | The stack's own MQTT broker, published on a free localhost port (`nspm-dev up` prints it) |
| `nspm` | NSPanelManager built from this checkout, on `http://localhost:8010` |
| `sim` | Simulated NSPanels ([`nspanel_sim/nspanel_sim.py`](nspanel_sim/nspanel_sim.py)) |

The stack has its own broker, so it never touches real panels and can run next to a
production install. A fresh stack seeds its database ([`seed.py`](seed.py)): MQTT settings
pointing at `mosquitto`, a room, and the simulated panels, already accepted.

## Usage

```bash
docker/dev/nspm-dev up          # first start builds the image and MQTTManager; slow once
docker/dev/nspm-dev logs nspm   # follow it
docker/dev/nspm-dev logs sim    # what the simulated panels receive, one JSON line per message
```

Change MQTTManager code, then:

```bash
docker/dev/nspm-dev rebuild         # incremental build + restart of MQTTManager
docker/dev/nspm-dev rebuild --full  # after conanfile.py changes
docker/dev/nspm-dev watch           # rebuild on every save
```

The web app (`docker/web`) is mounted in and served by Django's dev server, so Python and
template changes apply without a rebuild.

Other commands:

```bash
docker/dev/nspm-dev send '{"nspanel_id": 1, "button_pressed": {"button_id": 1}}'  # a command, as a panel sends it
docker/dev/nspm-dev shell    # bash in the nspm container
docker/dev/nspm-dev reset    # delete the database; the next `up` seeds a fresh one
docker/dev/nspm-dev down
```

## Settings

Environment variables, read by `nspm-dev up`:

| Variable | Default | |
|---|---|---|
| `NSPM_DEV_PORT` | `8010` | Web UI port on the host |
| `NSPM_DEV_MQTT_PORT` | picked by Docker | Broker port on the host (localhost only) |
| `NSPM_DEV_SIM_PANELS` | `1` | Number of simulated panels (MACs `02:00:00:00:00:01`, …) |
| `NSPM_CONAN_CACHE` | a volume | Host directory for Conan packages, to share with other checkouts |

With `sudo`, keep them with `sudo --preserve-env=NSPM_CONAN_CACHE,...`.

## The simulated panel

`nspanel_sim.py` implements the panel side of the MQTT protocol: registration, config,
online status and status reports. It also re-registers when the manager restarts. It does
not run the firmware or the Nextion UI, so firmware and UI changes still need a real panel.

It compiles the `.proto` files in `docker/protobuf` when it starts, so after a proto change
restart it with `nspm-dev compose restart sim`. It also runs outside Docker:

```bash
pip install -r docker/dev/nspanel_sim/requirements.txt
python docker/dev/nspanel_sim/nspanel_sim.py --broker localhost --port <broker port> run --watch-manager
```
