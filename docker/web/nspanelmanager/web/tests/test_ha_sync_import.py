"""M2b of the Home Assistant sync: label setting, entity candidates and bulk import
(web/rest_v2/home_assistant_sync.py). Home Assistant is mocked at the template fetch."""

import json
from unittest import mock

import requests

from web.entity_data import build_entity_data_from_state
from web.models import Entity, Room, RoomEntitiesPage
from web.settings_helper import set_setting_value

from .harness import NSPMTestCase

AREAS = [{"area_id": "kitchen", "name": "Kitchen"}, {"area_id": "living_room", "name": "Living Room"}, {"area_id": "hall", "name": "Hallway"}, {"area_id": "attic", "name": "Attic"}]
LABELS = [{"label_id": "acmax", "name": "ACMax"}, {"label_id": "nspm_ignore", "name": "NSPM ignore"}]


def ent(eid, area="kitchen", name=None, hidden=False, labels=(), **attributes):
    return {"entity_id": eid, "friendly_name": name or eid, "attributes": attributes, "area_id": area, "hidden": hidden, "labels": list(labels)}


def ha_response(text, status=200):
    response = mock.Mock()
    response.status_code = status
    response.text = text
    return response


class ImportTestCase(NSPMTestCase):
    def setUp(self):
        super().setUp()
        self.entities = []
        patcher = mock.patch(
            "web.home_assistant_api.requests.post",
            side_effect=lambda *a, **k: ha_response(json.dumps({"areas": AREAS, "labels": LABELS, "entities": self.entities})),
        )
        self.post_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def ha_down(self, status=500, text="boom"):
        self.post_mock.side_effect = lambda *a, **k: ha_response(text, status)

    def linked_room(self, name, area, order=0):
        room = self.make_room(name)
        room.home_assistant_link = Room.HomeAssistantLink.LINKED
        room.home_assistant_area_id = area
        room.displayOrder = order
        room.save()
        return room


class SettingTests(ImportTestCase):
    def test_round_trips_through_v2_settings(self):
        response = self.patch_json("/rest/v2/settings", {"home_assistant_sync_exclude_labels": " nspm_ignore, acmax "})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["home_assistant_sync_exclude_labels"], "nspm_ignore, acmax")
        self.assertEqual(self.client.get("/rest/v2/settings").json()["home_assistant_sync_exclude_labels"], "nspm_ignore, acmax")

    def test_type_checked(self):
        self.assertEqual(self.patch_json("/rest/v2/settings", {"home_assistant_sync_exclude_labels": ["a"]}).status_code, 400)

    def test_setting_excludes_labels_from_candidates(self):
        self.linked_room("Kitchen", "kitchen")
        self.entities = [ent("light.a", labels=["nspm_ignore"]), ent("light.b")]
        self.patch_json("/rest/v2/settings", {"home_assistant_sync_exclude_labels": "nspm_ignore"})
        ids = [c["entity_id"] for c in self.client.get(CAND).json()["candidates"]]
        self.assertEqual(ids, ["light.b"])


class LabelsTests(ImportTestCase):
    def test_lists_labels_sorted(self):
        response = self.client.get("/rest/v2/home_assistant/labels")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"label_id": "acmax", "name": "ACMax"}, {"label_id": "nspm_ignore", "name": "NSPM ignore"}])

    def test_502(self):
        self.ha_down(401, "401: Unauthorized")
        response = self.client.get("/rest/v2/home_assistant/labels")
        self.assertEqual(response.status_code, 502)
        self.assertIn("Unauthorized", response.json()["detail"])


CAND = "/rest/v2/home_assistant/entity_candidates"


class CandidatesTests(ImportTestCase):
    def get(self, **params):
        response = self.client.get(CAND, params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def ids(self, **params):
        return [c["entity_id"] for c in self.get(**params)["candidates"]]

    def test_row_shape_and_name_suggestion(self):
        room = self.linked_room("Kitchen", "kitchen")
        self.entities = [ent("light.kitchen_island", name="Kitchen Island Light", labels=["acmax"], supported_color_modes=["brightness"])]
        data = self.get()
        self.assertEqual(
            data,
            {
                "candidates": [
                    {
                        "entity_id": "light.kitchen_island",
                        "ha_name": "Kitchen Island Light",
                        "suggested_name": "Island Light",
                        "entity_type": "light",
                        "room_id": room.id,
                        "room_name": "Kitchen",
                        "area_id": "kitchen",
                        "hidden": False,
                        "is_group": False,
                        "labels": ["acmax"],
                        "already_imported_room_id": None,
                    }
                ],
                "entities_without_area": 0,
                "excluded_by_label": 0,
            },
        )

    def test_area_name_is_stripped_when_room_is_named_differently(self):
        self.linked_room("Cooking", "kitchen")
        self.entities = [ent("light.a", name="Kitchen Main Lights")]
        self.assertEqual(self.get()["candidates"][0]["suggested_name"], "Main Lights")

    def test_only_linked_rooms_are_listed(self):
        self.linked_room("Kitchen", "kitchen")
        unset = self.make_room("Living Room")
        none_room = self.make_room("Hallway")
        none_room.home_assistant_link = Room.HomeAssistantLink.NONE
        none_room.save()
        self.entities = [ent("light.k"), ent("light.l", area="living_room"), ent("light.h", area="hall"), ent("light.x", area="unknown_area")]
        self.assertEqual(self.ids(), ["light.k"])
        self.assertEqual(unset.home_assistant_link, Room.HomeAssistantLink.UNSET)

    def test_hidden_flag(self):
        self.linked_room("Kitchen", "kitchen")
        self.entities = [ent("light.a"), ent("light.b", hidden=True)]
        self.assertEqual(self.ids(), ["light.a"])
        self.assertEqual(self.ids(include_hidden="false"), ["light.a"])
        rows = self.get(include_hidden="true")["candidates"]
        self.assertEqual([(r["entity_id"], r["hidden"]) for r in rows], [("light.a", False), ("light.b", True)])

    def test_light_groups_flag(self):
        self.linked_room("Kitchen", "kitchen")
        self.entities = [ent("light.a"), ent("light.grp", entity_id=["light.a", "light.c"]), ent("cover.grp", entity_id=["x"])]
        self.assertEqual(self.ids(), ["light.a", "cover.grp"])  # only light.* with entity_id is a group
        rows = {r["entity_id"]: r for r in self.get(include_groups="true")["candidates"]}
        self.assertEqual(set(rows), {"cover.grp", "light.a", "light.grp"})
        self.assertTrue(rows["light.grp"]["is_group"])
        self.assertFalse(rows["light.a"]["is_group"])

    def test_imported_flag_and_other_room(self):
        kitchen = self.linked_room("Kitchen", "kitchen")
        other = self.make_room("Elsewhere")
        self.make_light(other, "Moved", home_assistant_name="light.a")
        self.entities = [ent("light.a"), ent("light.b")]
        self.assertEqual(self.ids(), ["light.b"])
        rows = {r["entity_id"]: r for r in self.get(include_imported="true")["candidates"]}
        self.assertEqual(rows["light.a"]["already_imported_room_id"], other.id)
        self.assertEqual(rows["light.a"]["room_id"], kitchen.id)
        self.assertIsNone(rows["light.b"]["already_imported_room_id"])

    def test_label_exclusion_is_always_on_and_counted(self):
        self.linked_room("Kitchen", "kitchen")
        set_setting_value("home_assistant_sync_exclude_labels", "nspm_ignore, other")
        self.entities = [ent("light.a", labels=["acmax", "nspm_ignore"]), ent("light.b", labels=["other"]), ent("light.c", labels=["acmax"])]
        for flags in ({}, {"include_hidden": "true", "include_groups": "true", "include_imported": "true"}):
            data = self.get(**flags)
            self.assertEqual([c["entity_id"] for c in data["candidates"]], ["light.c"])
            self.assertEqual(data["excluded_by_label"], 2)

    def test_blank_setting_excludes_nothing(self):
        self.linked_room("Kitchen", "kitchen")
        set_setting_value("home_assistant_sync_exclude_labels", " , ")
        self.entities = [ent("light.a", labels=["x"])]
        self.assertEqual(self.get()["excluded_by_label"], 0)
        self.assertEqual(self.ids(), ["light.a"])

    def test_entities_without_area_are_counted(self):
        self.linked_room("Kitchen", "kitchen")
        set_setting_value("home_assistant_sync_exclude_labels", "nspm_ignore")
        self.entities = [ent("light.a"), ent("light.n1", area=None), ent("cover.n2", area=None), ent("light.n3", area=None, hidden=True), ent("light.n4", area=None, labels=["nspm_ignore"])]
        data = self.get()
        self.assertEqual(data["entities_without_area"], 2)  # hidden and label-excluded ones are not counted
        self.assertEqual(self.get(include_hidden="true")["entities_without_area"], 3)
        self.assertEqual(self.ids(), ["light.a"])

    def test_unsupported_domains_are_ignored(self):
        self.linked_room("Kitchen", "kitchen")
        self.entities = [ent("switch.a"), ent("light.b")]
        self.assertEqual(self.ids(), ["light.b"])

    def test_sort_order(self):
        second = self.linked_room("Second", "living_room", order=2)
        first = self.linked_room("First", "kitchen", order=1)
        self.entities = [
            ent("climate.t", area="living_room", name="Thermo"),
            ent("media_player.m", area="kitchen", name="Zed"),
            ent("light.z", area="kitchen", name="zebra"),
            ent("light.b", area="kitchen", name="Banana"),
            ent("light.a", area="living_room", name="Apple"),
            ent("cover.c", area="kitchen", name="Blind"),
            ent("media_player.a", area="kitchen", name="Amp"),
            ent("light.l", area="kitchen", name="apple"),
        ]
        rows = self.get()["candidates"]
        self.assertEqual([r["entity_id"] for r in rows], ["light.l", "light.b", "light.z", "cover.c", "media_player.a", "media_player.m", "light.a", "climate.t"])
        self.assertEqual([r["room_id"] for r in rows], [first.id] * 6 + [second.id] * 2)

    def test_invalid_boolean_is_400(self):
        self.assertEqual(self.client.get(CAND, {"include_hidden": "maybe"}).status_code, 400)

    def test_ha_failure_is_502(self):
        self.ha_down(500, "boom")
        response = self.client.get(CAND)
        self.assertEqual(response.status_code, 502)
        self.assertIn("boom", response.json()["detail"])
        self.post_mock.side_effect = requests.ConnectionError("refused")
        self.assertEqual(self.client.get(CAND).status_code, 502)


IMPORT = "/rest/v2/home_assistant/import"


class ImportTests(ImportTestCase):
    def item(self, entity_id, room, entity_type=None, name="Name"):
        entity_type = entity_type or {"climate": "thermostat"}.get(entity_id.split(".")[0], entity_id.split(".")[0])
        return {"entity_id": entity_id, "room_id": room.id, "entity_type": entity_type, "friendly_name": name}

    def do_import(self, *items, status=201):
        response = self.post_json(IMPORT, {"items": list(items)})
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def assert_400(self, body, text):
        before = Entity.objects.count()
        response = self.post_json(IMPORT, body)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(text, str(response.json()))
        self.assertEqual(Entity.objects.count(), before)
        self.assertManagerNotReloaded()

    def test_happy_path_all_four_types(self):
        room = self.linked_room("Kitchen", "kitchen")
        self.entities = [
            ent("light.l", supported_color_modes=["color_temp", "xy"]),
            ent("cover.c"),
            ent("media_player.m"),
            ent("climate.t", hvac_modes=["heat", "off"], fan_modes=["auto"], target_temp_step=0.5),
        ]
        data = self.do_import(self.item("light.l", room, name="Lamp"), self.item("cover.c", room, name="Blind"), self.item("media_player.m", room, name="TV"), self.item("climate.t", room, name="Heat"))

        self.assertEqual(data["skipped"], [])
        self.assertEqual(data["pages_added"], 0)
        self.assertEqual([c["entity_id"] for c in data["created"]], ["light.l", "cover.c", "media_player.m", "climate.t"])
        page = self.entities_page(room)
        self.assertEqual([(c["page_id"], c["position"]) for c in data["created"]], [(page.id, 0), (page.id, 1), (page.id, 2), (page.id, 3)])
        for created, entity in zip(data["created"], self.entities):
            row = Entity.objects.get(pk=created["entity_pk"])
            entity_type = row.entity_type
            self.assertEqual(row.room_id, room.id)
            self.assertEqual(row.entities_page_id, page.id)
            self.assertEqual(row.entity_data, build_entity_data_from_state(entity_type, {"entity_id": entity["entity_id"], "attributes": entity["attributes"]}))
            self.assertEqual(row.entity_data["controller"], "home_assistant")
            self.assertLoadableByManager(row)
        self.assertEqual(Entity.objects.get(entity_data__home_assistant_name="light.l").friendly_name, "Lamp")
        light = Entity.objects.get(entity_data__home_assistant_name="light.l").entity_data
        self.assertTrue(light["can_dim"] and light["can_color_temperature"] and light["can_rgb"])
        thermostat = Entity.objects.get(entity_data__home_assistant_name="climate.t")
        self.assertEqual((thermostat.entity_type, thermostat.entity_data["step_size"]), ("thermostat", 0.5))
        self.assertManagerReloaded(times=1)

    def test_fills_free_slots_then_adds_a_page_of_the_last_size(self):
        room = self.linked_room("Kitchen", "kitchen")  # one 4-slot page
        self.make_light(room, "A", slot=0, home_assistant_name="light.existing_a")
        self.make_light(room, "B", slot=2, home_assistant_name="light.existing_b")
        self.entities = [ent(f"light.n{i}") for i in range(5)]
        data = self.do_import(*[self.item(f"light.n{i}", room) for i in range(5)])
        first = self.entities_page(room)
        pages = list(RoomEntitiesPage.objects.filter(room=room, is_scenes_page=False).order_by("display_order", "id"))
        self.assertEqual(len(pages), 2)
        self.assertEqual((pages[1].page_type, data["pages_added"]), (4, 1))  # N=3, S=4 -> one 4
        placed = [(c["page_id"], c["position"]) for c in data["created"]]
        self.assertEqual(placed, [(first.id, 1), (first.id, 3), (pages[1].id, 0), (pages[1].id, 1), (pages[1].id, 2)])
        self.assertManagerReloaded(times=1)

    def test_page_size_examples(self):
        for count, sizes in ((3, [4]), (6, [8]), (15, [12, 4])):
            with self.subTest(count=count):
                room = self.linked_room(f"Room{count}", "kitchen")
                page = self.entities_page(room)
                for slot in range(4):
                    self.make_light(room, f"L{slot}", slot=slot, page=page, home_assistant_name=f"light.old{count}_{slot}")
                self.entities = [ent(f"light.n{i}") for i in range(count)]
                data = self.do_import(*[self.item(f"light.n{i}", room) for i in range(count)])
                pages = list(RoomEntitiesPage.objects.filter(room=room, is_scenes_page=False).order_by("display_order", "id"))
                self.assertEqual([p.page_type for p in pages[1:]], sizes)
                self.assertEqual(data["pages_added"], len(sizes))
                Room.objects.filter(pk=room.pk).update(home_assistant_area_id="")
                Entity.objects.all().delete()

    def test_multiple_rooms_in_one_request_keep_item_order(self):
        kitchen = self.linked_room("Kitchen", "kitchen", 1)
        living = self.linked_room("Living", "living_room", 2)
        self.entities = [ent("light.k1"), ent("light.l1", area="living_room"), ent("light.k2"), ent("cover.l2", area="living_room")]
        data = self.do_import(self.item("light.k1", kitchen), self.item("light.l1", living), self.item("light.k2", kitchen), self.item("cover.l2", living))
        self.assertEqual([(c["entity_id"], c["room_id"], c["position"]) for c in data["created"]], [("light.k1", kitchen.id, 0), ("light.l1", living.id, 0), ("light.k2", kitchen.id, 1), ("cover.l2", living.id, 1)])
        self.assertManagerReloaded(times=1)

    def test_concurrent_import_is_skipped_not_failed(self):
        room = self.linked_room("Kitchen", "kitchen")
        other = self.make_room("Other")
        self.entities = [ent("light.a"), ent("light.b")]
        real = self.post_mock.side_effect

        def racing(*args, **kwargs):  # someone imports light.a after the listing was made, in any room
            if not Entity.objects.filter(entity_data__home_assistant_name="light.a").exists():
                self.make_light(other, "Taken", home_assistant_name="light.a")
            return real(*args, **kwargs)

        self.post_mock.side_effect = racing
        data = self.do_import(self.item("light.a", room), self.item("light.b", room))
        self.assertEqual(data["skipped"], [{"entity_id": "light.a", "reason": "already_imported"}])
        self.assertEqual([(c["entity_id"], c["position"]) for c in data["created"]], [("light.b", 0)])
        self.assertManagerReloaded(times=1)

    def test_all_skipped_does_not_reload(self):
        room = self.linked_room("Kitchen", "kitchen")
        self.entities = [ent("light.a")]
        self.make_light(self.make_room("Other"), "Taken", home_assistant_name="light.a")
        data = self.do_import(self.item("light.a", room))
        self.assertEqual((data["created"], data["pages_added"]), ([], 0))
        self.assertEqual(len(data["skipped"]), 1)
        self.assertManagerNotReloaded()
        self.assertEqual(RoomEntitiesPage.objects.filter(room=room).count(), 2)

    def test_atomic_on_failure(self):
        a = self.linked_room("Kitchen", "kitchen", 1)
        b = self.linked_room("Living", "living_room", 2)
        for room in (a, b):  # full pages, so each import adds a page
            for slot in range(4):
                self.make_light(room, f"L{slot}", slot=slot, home_assistant_name=f"light.old_{room.id}_{slot}")
        self.entities = [ent("light.k"), ent("light.l", area="living_room")]
        entities_before, pages_before = Entity.objects.count(), RoomEntitiesPage.objects.count()
        from web.entity_placement import place_in_room as real

        calls = []

        def flaky(room, count):
            calls.append(room.id)
            if len(calls) == 2:
                raise RuntimeError("db went away")
            return real(room, count)

        with mock.patch("web.rest_v2.home_assistant_sync.place_in_room", side_effect=flaky):
            response = self.post_json(IMPORT, {"items": [self.item("light.k", a), self.item("light.l", b)]})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(calls, [a.id, b.id])
        self.assertEqual((Entity.objects.count(), RoomEntitiesPage.objects.count()), (entities_before, pages_before))
        self.assertManagerNotReloaded()

    def test_validation_errors(self):
        room = self.linked_room("Kitchen", "kitchen")
        unlinked = self.make_room("Unlinked")
        self.entities = [ent("light.a"), ent("light.elsewhere", area="living_room"), ent("light.noarea", area=None)]
        ok = self.item("light.a", room)

        self.assert_400({"items": []}, "items")
        self.assert_400({}, "items")
        self.assert_400({"items": [ok], "extra": 1}, "Unknown field")
        self.assert_400({"items": [{**ok, "extra": 1}]}, "Unknown field")
        self.assert_400({"items": [{**ok, "room_id": 99999}]}, "unknown room")
        self.assert_400({"items": [self.item("light.a", unlinked)]}, "not linked")
        self.assert_400({"items": [{**ok, "entity_type": "cover"}]}, 'must be "light"')
        self.assert_400({"items": [{**ok, "entity_type": "switch"}]}, "entity_type")
        self.assert_400({"items": [{**ok, "friendly_name": "   "}]}, "friendly_name")
        self.assert_400({"items": [{**ok, "friendly_name": "x" * 256}]}, "friendly_name")
        self.assert_400({"items": [{**ok, "friendly_name": 5}]}, "friendly_name")
        self.assert_400({"items": [{**ok, "room_id": "1"}]}, "room_id")
        self.assert_400({"items": [ok, ok]}, "Duplicate entity ids")
        self.assert_400({"items": [self.item("light.elsewhere", room)]}, "not in the Home Assistant area")
        self.assert_400({"items": [self.item("light.noarea", room)]}, "not in the Home Assistant area")
        self.assert_400({"items": [self.item("light.gone", room)]}, "not found in Home Assistant")
        self.assert_400({"items": [{**self.item("switch.a", room), "entity_type": "light"}]}, "not supported")

    def test_name_is_trimmed_and_max_length_accepted(self):
        room = self.linked_room("Kitchen", "kitchen")
        self.entities = [ent("light.a"), ent("light.b")]
        self.do_import(self.item("light.a", room, name="  Lamp  "), self.item("light.b", room, name="y" * 255))
        self.assertEqual(Entity.objects.get(entity_data__home_assistant_name="light.a").friendly_name, "Lamp")
        self.assertEqual(len(Entity.objects.get(entity_data__home_assistant_name="light.b").friendly_name), 255)

    def test_validation_failure_for_any_item_creates_nothing(self):
        room = self.linked_room("Kitchen", "kitchen")
        self.entities = [ent("light.a")]
        self.assert_400({"items": [self.item("light.a", room), self.item("light.gone", room)]}, "not found")
        self.assertFalse(Entity.objects.filter(entity_data__home_assistant_name="light.a").exists())

    def test_ha_failure_is_502(self):
        room = self.linked_room("Kitchen", "kitchen")
        self.ha_down(500, "boom")
        response = self.post_json(IMPORT, {"items": [self.item("light.a", room)]})
        self.assertEqual(response.status_code, 502)
        self.assertIn("boom", response.json()["detail"])
        self.assertManagerNotReloaded()
