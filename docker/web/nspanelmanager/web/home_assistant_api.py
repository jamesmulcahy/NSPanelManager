import json
import logging
import traceback

import environ
import requests

from web.settings_helper import get_setting_with_default


def get_all_home_assistant_items(filter={}):
    return_json = {"items": [], "errors": []}

    if get_setting_with_default("home_assistant_token") == "" or get_setting_with_default("home_assistant_address") == "":
        return_json["errors"].append("Home Assistant address and/or access token not configured")
        return return_json

    home_assistant_request_headers = {
        "Authorization": "Bearer " + get_setting_with_default("home_assistant_token"),
        "content-type": "application/json",
    }
    try:
        environment = environ.Env()
        if "IS_HOME_ASSISTANT_ADDON" in environment and environment("IS_HOME_ASSISTANT_ADDON") == "true":
            home_assistant_api_address = get_setting_with_default("home_assistant_address") + "/core/api/states"
        else:
            home_assistant_api_address = get_setting_with_default("home_assistant_address") + "/api/states"
        logging.debug("Trying to get Home Assistant entities via api address: " + home_assistant_api_address)
        home_assistant_response = requests.get(home_assistant_api_address, headers=home_assistant_request_headers, timeout=5, verify=False)
        if home_assistant_response.status_code == 200:
            for entity in home_assistant_response.json():
                add_entity = False
                if len(filter) == 0:
                    add_entity = True
                elif "type" in filter:
                    entity_type = entity["entity_id"].split(".")[0]
                    add_entity = entity_type in filter["type"]

                if add_entity:
                    data = {
                        "type": "home_assistant",
                        "label": entity["entity_id"],
                        "item_id": entity["entity_id"],
                        "item": entity,
                    }
                    if "friendly_name" in entity["attributes"]:
                        data["label"] = entity["attributes"]["friendly_name"]
                    return_json["items"].append(data)
        else:
            return_json["errors"].append("Failed to get Home Assistant lights, got return code: " + str(home_assistant_response.status_code))
            print("ERROR! Got status code other than 200. Got code: " + str(home_assistant_response.status_code))
    except Exception as e:
        return_json["errors"].append("Failed to get Home Assistant lights: " + str(traceback.format_exc()))
        logging.exception("Failed to get Home Assistant lights!")
    return return_json


class HomeAssistantError(Exception):
    """Home Assistant could not be reached or returned something unusable. The message is meant for the user."""


SYNC_ENTITY_DOMAINS = ("light", "media_player", "cover", "climate")

# One render returns everything the sync needs. area_id() also covers areas an entity inherits from its device.
_SYNC_TEMPLATE = """\
{%- set ns = namespace(areas=[], labels=[], entities=[]) -%}
{%- for a in areas() -%}
  {%- set ns.areas = ns.areas + [{"area_id": a, "name": area_name(a)}] -%}
{%- endfor -%}
{%- for l in labels() -%}
  {%- set ns.labels = ns.labels + [{"label_id": l, "name": label_name(l)}] -%}
{%- endfor -%}
{%- for s in states if s.domain in ["light", "media_player", "cover", "climate"] -%}
  {%- set ns.entities = ns.entities + [{
        "entity_id": s.entity_id,
        "area_id": area_id(s.entity_id),
        "hidden": is_hidden_entity(s.entity_id),
        "labels": labels(s.entity_id)
      }] -%}
{%- endfor -%}
{{ {"areas": ns.areas, "labels": ns.labels, "entities": ns.entities} | tojson }}"""


def _is_home_assistant_addon():
    environment = environ.Env()
    return "IS_HOME_ASSISTANT_ADDON" in environment and environment("IS_HOME_ASSISTANT_ADDON") == "true"


def fetch_home_assistant_registry():
    """Fetch areas, labels and the supported entities (with their area, hidden flag and labels) from Home Assistant.

    Returns {"areas": [{area_id, name}], "labels": [{label_id, name}], "entities": [{entity_id, area_id, hidden, labels}]}.
    area_id is None for an entity without an area. Raises HomeAssistantError for anything that goes wrong, so a
    failure can never be mistaken for "Home Assistant has no areas".
    """
    address = get_setting_with_default("home_assistant_address")
    token = get_setting_with_default("home_assistant_token")
    if address == "" or token == "":
        raise HomeAssistantError("Home Assistant address and/or access token not configured")

    prefix = "/core/api" if _is_home_assistant_addon() else "/api"
    url = address + prefix + "/template"
    headers = {"Authorization": "Bearer " + token, "content-type": "application/json"}
    try:
        response = requests.post(url, headers=headers, json={"template": _SYNC_TEMPLATE}, timeout=10, verify=False)
    except requests.RequestException as e:
        raise HomeAssistantError(f"Could not reach Home Assistant: {e}") from e

    if response.status_code != 200:
        detail = (getattr(response, "text", "") or "").strip()[:500]
        raise HomeAssistantError(f"Home Assistant returned status {response.status_code}" + (f": {detail}" if detail else ""))

    try:
        data = json.loads(response.text)
    except (TypeError, ValueError) as e:
        raise HomeAssistantError(f"Home Assistant returned an unreadable template result: {e}") from e

    if not isinstance(data, dict) or not all(isinstance(data.get(key), list) for key in ("areas", "labels", "entities")):
        raise HomeAssistantError("Home Assistant returned an unexpected template result")

    try:
        return {
            "areas": [{"area_id": a["area_id"], "name": a["name"] or a["area_id"]} for a in data["areas"]],
            "labels": [{"label_id": l["label_id"], "name": l["name"] or l["label_id"]} for l in data["labels"]],
            "entities": [
                {"entity_id": e["entity_id"], "area_id": e["area_id"] or None, "hidden": bool(e["hidden"]), "labels": list(e["labels"] or [])}
                for e in data["entities"]
                if e["entity_id"].split(".")[0] in SYNC_ENTITY_DOMAINS
            ],
        }
    except (KeyError, TypeError, AttributeError) as e:
        raise HomeAssistantError(f"Home Assistant returned an unexpected template result: {e!r}") from e
