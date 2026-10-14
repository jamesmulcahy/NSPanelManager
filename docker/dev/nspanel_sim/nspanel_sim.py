#!/usr/bin/env python3
"""Simulated NSPanels for the NSPanelManager dev stack.

`run` speaks the panel side of the MQTT protocol well enough for MQTTManager to treat each
simulated panel as a real one: it sends register_request until the manager accepts it,
receives its config, reports itself online and sends status reports. It re-registers when
the manager comes back online, as the firmware does. Everything a panel receives is printed
as one JSON line, decoded where the topic's protobuf type is known.

`send` publishes one NSPanelMQTTManagerCommand, given as JSON, as if a panel had sent it.

It does not run the panel firmware or the Nextion UI; use a real panel to test those.

The .proto files are compiled at startup, so a changed proto only needs a restart.
"""

import argparse
import importlib
import importlib.resources
import json
import pathlib
import re
import sys
import tempfile
import threading
import time

import paho.mqtt.client as mqtt
from google.protobuf.json_format import MessageToDict, ParseDict

REGISTER_TOPIC = "nspanel/mqttmanager/command"
REGISTER_INTERVAL = 5  # Seconds; the same as the firmware.
STATUS_REPORT_INTERVAL = 30


def load_protobufs(proto_dir):
    from grpc_tools import protoc

    out_dir = tempfile.mkdtemp(prefix="nspm_proto_")
    protos = sorted(path.name for path in pathlib.Path(proto_dir).glob("*.proto"))
    well_known = importlib.resources.files("grpc_tools") / "_proto"
    if protoc.main(["protoc", f"-I{proto_dir}", f"-I{well_known}", f"--python_out={out_dir}", *protos]) != 0:
        sys.exit(f"Failed to compile the .proto files in {proto_dir}")
    sys.path.insert(0, out_dir)
    return importlib.import_module("protobuf_nspanel_pb2"), importlib.import_module("protobuf_nspanel_entity_pb2")


def sim_mac(number):
    # Locally administered MACs, so they can never belong to a real panel. seed.py uses the same.
    return f"02:00:00:00:00:{number:02X}"


def emit(**fields):
    print(json.dumps({"ts": round(time.time(), 3), **fields}), flush=True)


def to_dict(message):
    return MessageToDict(message, preserving_proto_field_name=True)


class SimPanel:
    def __init__(self, args, number, nspanel_pb, entity_pb):
        self.number = number
        self.mac = sim_mac(number)
        self.name = f"Sim Panel {number}"
        self.nspanel_pb = nspanel_pb
        self.status_topic = f"nspanel/{self.mac}/status"
        self.command_topic = f"nspanel/{self.mac}/command"
        self.config_topic = None
        self.manager_prefix = None
        self.watch_manager = args.watch_manager
        self.manager_decoders = [
            (re.compile(r"^status/weather$"), nspanel_pb.NSPanelWeatherUpdate),
            (re.compile(r"^(room/\d+/state|all_rooms_status)$"), nspanel_pb.NSPanelRoomStatus),
            (re.compile(r"^entities/[a-z_]+/\d+/state$"), entity_pb.NSPanelEntityState),
            (re.compile(r"^entity_pages/\d+/state$"), nspanel_pb.NSPanelRoomEntitiesPage),
            (re.compile(r"^command$"), nspanel_pb.NSPanelMQTTManagerCommand),
        ]
        self.accepted = threading.Event()
        self.manager_online = None  # Unknown until the manager's status arrives.

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"nspanel-sim-{self.mac.replace(':', '')}")
        self.client.will_set(self.status_topic, json.dumps({"state": "offline"}), retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 10)
        self.client.connect_async(args.broker, args.port)

    def start(self):
        self.client.loop_start()
        threading.Thread(target=self._register_loop, daemon=True).start()
        threading.Thread(target=self._status_report_loop, daemon=True).start()

    def _emit(self, **fields):
        emit(panel=self.name, **fields)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self._emit(event="connected", reason=str(reason_code))
        client.subscribe(self.command_topic)
        self._subscribe_manager_topics()
        client.publish(self.status_topic, json.dumps({"state": "online"}), retain=True)
        # Like the firmware, register again after every reconnect.
        self.accepted.clear()

    def _subscribe_manager_topics(self):
        if self.config_topic:
            self.client.subscribe(self.config_topic)
        if self.manager_prefix:
            self.client.subscribe(f"{self.manager_prefix}/#" if self.watch_manager else f"{self.manager_prefix}/status/status")

    def _register_loop(self):
        while True:
            if self.client.is_connected() and not self.accepted.is_set():
                request = {
                    "command": "register_request",
                    "mac_origin": self.mac,
                    "friendly_name": self.name,
                    "version": "sim",
                    "md5_firmware": "sim",
                    "md5_data_file": "sim",
                    "md5_tft_file": "sim",
                    "address": "127.0.0.1",
                    "model": "sonoff",
                }
                self.client.publish(REGISTER_TOPIC, json.dumps(request))
                self._emit(event="register_request")
            time.sleep(REGISTER_INTERVAL)

    def _status_report_loop(self):
        while True:
            if self.accepted.wait(timeout=1):
                self._publish_status_report()
                time.sleep(STATUS_REPORT_INTERVAL)

    def _publish_status_report(self):
        report = self.nspanel_pb.NSPanelStatusReport(
            nspanel_state=self.nspanel_pb.NSPanelStatusReport.ONLINE,
            rssi=-50,
            heap_used_pct=40,
            mac_address=self.mac,
            temperature=21.5,
            ip_address="127.0.0.1",
            md5_firmware="sim",
            md5_littlefs="sim",
            md5_tft_gui="sim",
        )
        self.client.publish(f"nspanel/{self.mac}/status_report", report.SerializeToString())

    def _on_message(self, client, userdata, message):
        topic, payload = message.topic, message.payload
        if topic == self.command_topic:
            self._handle_command(payload)
        elif topic == self.config_topic:
            config = self.nspanel_pb.NSPanelConfig()
            config.ParseFromString(payload)
            self._emit(topic=topic, format="protobuf:NSPanelConfig", value=to_dict(config))
        elif self.manager_prefix and topic == f"{self.manager_prefix}/status/status":
            self._handle_manager_status(payload.decode(errors="replace"))
        else:
            self._emit(topic=topic, **self._decode_manager_topic(topic, payload))

    def _handle_command(self, payload):
        try:
            data = json.loads(payload)
        except ValueError:
            self._emit(topic=self.command_topic, format="binary", value=payload.hex())
            return
        self._emit(topic=self.command_topic, format="json", value=data)
        if data.get("command") != "register_accept":
            return
        new_prefix = f"nspanel/mqttmanager_{data.get('address', '')}"
        new_config_topic = data.get("config_topic")
        if new_prefix != self.manager_prefix or new_config_topic != self.config_topic:
            for topic in (self.config_topic, self.manager_prefix and f"{self.manager_prefix}/#", self.manager_prefix and f"{self.manager_prefix}/status/status"):
                if topic:
                    self.client.unsubscribe(topic)
            self.manager_prefix, self.config_topic = new_prefix, new_config_topic
            self._subscribe_manager_topics()
        self.accepted.set()
        self._emit(event="accepted", config_topic=self.config_topic)

    def _handle_manager_status(self, status):
        self._emit(event="manager_status", value=status)
        online = status == "online"
        if online and self.manager_online is False:
            # The manager (re)started; it only sends config in reply to a register_request.
            self.accepted.clear()
        self.manager_online = online

    def _decode_manager_topic(self, topic, payload):
        rest = topic[len(self.manager_prefix) + 1 :] if self.manager_prefix and topic.startswith(self.manager_prefix + "/") else None
        for pattern, message_class in self.manager_decoders if rest is not None else ():
            if pattern.match(rest):
                message = message_class()
                try:
                    message.ParseFromString(payload)
                    return {"format": f"protobuf:{message_class.DESCRIPTOR.name}", "value": to_dict(message)}
                except Exception as exc:  # noqa: BLE001 - fall back to the raw payload
                    return {"format": "binary", "value": payload.hex(), "decode_error": str(exc)}
        try:
            return {"format": "text", "value": payload.decode()}
        except UnicodeDecodeError:
            return {"format": "binary", "value": payload.hex()}


def run(args, nspanel_pb, entity_pb):
    panels = [SimPanel(args, number, nspanel_pb, entity_pb) for number in range(1, args.count + 1)]
    for panel in panels:
        panel.start()
    emit(event="started", panels=[{"name": panel.name, "mac": panel.mac} for panel in panels], broker=f"{args.broker}:{args.port}")
    threading.Event().wait()


def send(args, nspanel_pb):
    command = ParseDict(json.loads(args.command), nspanel_pb.NSPanelMQTTManagerCommand())
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(args.broker, args.port)
    client.loop_start()
    topic = f"nspanel/mqttmanager_{args.manager_address}/command"
    client.publish(topic, command.SerializeToString(), qos=1).wait_for_publish(timeout=5)
    client.loop_stop()
    emit(event="sent", topic=topic, value=to_dict(command))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--proto-dir", default=str(pathlib.Path(__file__).resolve().parents[2] / "protobuf"))
    subcommands = parser.add_subparsers(dest="action")

    run_parser = subcommands.add_parser("run", help="Run simulated panels (the default)")
    run_parser.add_argument("--count", type=int, default=1, help="Number of panels; the dev stack seeds this many as accepted")
    run_parser.add_argument("--watch-manager", action="store_true", help="Also print everything the manager publishes under nspanel/mqttmanager_<address>/")

    send_parser = subcommands.add_parser("send", help="Send one NSPanelMQTTManagerCommand as a panel would")
    send_parser.add_argument("command", help='The command as JSON, e.g. \'{"nspanel_id": 1, "button_pressed": {"button_id": 1}}\'')
    send_parser.add_argument("--manager-address", default="nspm")

    parser.set_defaults(action="run", count=1, watch_manager=False)
    args = parser.parse_args()

    nspanel_pb, entity_pb = load_protobufs(args.proto_dir)
    if args.action == "send":
        send(args, nspanel_pb)
    else:
        run(args, nspanel_pb, entity_pb)


if __name__ == "__main__":
    main()
