"""M1 of the Home Assistant sync: room <-> area links (web/ha_area_matching.py, the template fetch in
web/home_assistant_api.py, web/rest_v2/home_assistant_sync.py and the Room fields of web/rest_v2/rooms.py)."""

import json
import os
from unittest import mock

import requests
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from web.ha_area_matching import normalise_name, suggest_area
from web.home_assistant_api import HomeAssistantError, fetch_home_assistant_registry
from web.models import IgnoredHomeAssistantArea, Room, RoomEntitiesPage

from .harness import NSPMTestCase

# The live area names (2026-11-16) the plan's matching table is based on.
LIVE_AREAS = [
    {"area_id": a, "name": n}
    for a, n in [
        ("alexs_bedroom", "Alex’s Bedroom"),
        ("olivers_bedroom", "Oliver’s Bedroom"),
        ("kitchen", "Kitchen"),
        ("laundry_room", "Laundry Room"),
        ("front_porch", "Front Porch"),
        ("foyer", "Foyer"),
        ("front_foyer", "Front Foyer"),
        ("living_room", "Living Room"),
        ("formal_living_room", "Formal Living Room"),
        ("master_bedroom", "Master Bedroom"),
        ("master_bathroom", "Master Bathroom"),
        ("guest_bathroom", "Guest Bathroom"),
        ("patio", "Patio"),
    ]
]


def template_result(areas=None, labels=None, entities=None):
    return json.dumps({"areas": areas if areas is not None else LIVE_AREAS, "labels": labels or [], "entities": entities or []})


def ha_response(text, status=200):
    response = mock.Mock()
    response.status_code = status
    response.text = text
    return response


class MatcherTests(NSPMTestCase):
    def suggest(self, name, areas=LIVE_AREAS):
        return suggest_area(name, areas)

    def test_normalise(self):
        self.assertEqual(normalise_name("  Oliver’s   Bedroom "), "oliver bedroom")
        self.assertEqual(normalise_name("Oliver's Bedroom"), "oliver bedroom")
        self.assertEqual(normalise_name("James' Room"), "james room")
        self.assertEqual(normalise_name("KITCHEN"), "kitchen")

    def test_exact_match(self):
        s = self.suggest("kitchen")
        self.assertEqual((s.area_id, s.ambiguous), ("kitchen", False))

    def test_prefix_match(self):
        self.assertEqual(self.suggest("Laundry").area_id, "laundry_room")

    def test_suffix_match(self):
        self.assertEqual(self.suggest("Porch").area_id, "front_porch")

    def test_curly_apostrophe_possessive(self):
        self.assertEqual(self.suggest("Oliver Bedroom").area_id, "olivers_bedroom")
        self.assertEqual(self.suggest("Alex Bedroom").area_id, "alexs_bedroom")

    def test_exact_wins_but_is_flagged_when_another_candidate_exists(self):
        s = self.suggest("Foyer")
        self.assertEqual(s.area_id, "foyer")
        self.assertTrue(s.ambiguous)
        self.assertEqual(s.candidates, ["foyer", "front_foyer"])

    def test_foyer_is_unambiguous_once_the_exact_area_is_taken(self):
        areas = [a for a in LIVE_AREAS if a["area_id"] != "foyer"]
        s = self.suggest("Foyer", areas)
        self.assertEqual((s.area_id, s.ambiguous), ("front_foyer", False))

    def test_several_partial_matches_suggest_nothing(self):
        s = self.suggest("Bathroom")
        self.assertIsNone(s.area_id)
        self.assertTrue(s.ambiguous)
        self.assertEqual(s.candidates, ["master_bathroom", "guest_bathroom"])

    def test_several_exact_matches_suggest_nothing(self):
        s = self.suggest("Den", [{"area_id": "a", "name": "Den"}, {"area_id": "b", "name": "den"}])
        self.assertIsNone(s.area_id)
        self.assertTrue(s.ambiguous)

    def test_no_match(self):
        s = self.suggest("Garden")
        self.assertEqual((s.area_id, s.ambiguous, s.candidates), (None, False, []))

    def test_matches_whole_words_only(self):
        self.assertIsNone(self.suggest("Pat").area_id)

    def test_blank_room_name(self):
        self.assertIsNone(suggest_area("  ", LIVE_AREAS).area_id)


class FetchTests(NSPMTestCase):
    def post(self, **kwargs):
        return mock.patch("web.home_assistant_api.requests.post", **kwargs)

    def test_parses_the_template_result(self):
        result = template_result(
            areas=[{"area_id": "kitchen", "name": "Kitchen"}],
            labels=[{"label_id": "acmax", "name": "ACMax"}],
            entities=[
                {"entity_id": "light.a", "area_id": "kitchen", "hidden": False, "labels": ["acmax"]},
                {"entity_id": "cover.b", "friendly_name": "Blind B", "attributes": {"x": 1}, "area_id": None, "hidden": True, "labels": []},
                {"entity_id": "switch.not_supported", "area_id": "kitchen", "hidden": False, "labels": []},
            ],
        )
        with self.post(return_value=ha_response(result)) as post:
            registry = fetch_home_assistant_registry()

        self.assertEqual(registry["areas"], [{"area_id": "kitchen", "name": "Kitchen"}])
        self.assertEqual(registry["labels"], [{"label_id": "acmax", "name": "ACMax"}])
        self.assertEqual(
            registry["entities"],
            [
                {"entity_id": "light.a", "friendly_name": "light.a", "attributes": {}, "area_id": "kitchen", "hidden": False, "labels": ["acmax"]},
                {"entity_id": "cover.b", "friendly_name": "Blind B", "attributes": {"x": 1}, "area_id": None, "hidden": True, "labels": []},
            ],
        )
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://home-assistant.test/api/template")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertIn("template", kwargs["json"])
        self.assertIn("tojson", kwargs["json"]["template"])
        self.assertIsNotNone(kwargs["timeout"])
        self.assertFalse(kwargs["verify"])

    def test_addon_uses_the_core_prefix(self):
        with mock.patch.dict(os.environ, {"IS_HOME_ASSISTANT_ADDON": "true"}), self.post(return_value=ha_response(template_result())) as post:
            fetch_home_assistant_registry()
        self.assertEqual(post.call_args[0][0], "http://home-assistant.test/core/api/template")

    def test_empty_area_name_falls_back_to_the_id(self):
        with self.post(return_value=ha_response(template_result(areas=[{"area_id": "x", "name": None}]))):
            self.assertEqual(fetch_home_assistant_registry()["areas"], [{"area_id": "x", "name": "x"}])

    def test_not_configured(self):
        from web.settings_helper import set_setting_value

        set_setting_value("home_assistant_token", "")
        with self.post() as post, self.assertRaisesMessage(HomeAssistantError, "not configured"):
            fetch_home_assistant_registry()
        post.assert_not_called()

    def test_connection_error(self):
        with self.post(side_effect=requests.ConnectionError("refused")), self.assertRaisesMessage(HomeAssistantError, "Could not reach Home Assistant"):
            fetch_home_assistant_registry()

    def test_timeout(self):
        with self.post(side_effect=requests.Timeout("slow")), self.assertRaises(HomeAssistantError):
            fetch_home_assistant_registry()

    def test_http_error_carries_homeassistants_message(self):
        with self.post(return_value=ha_response("401: Unauthorized", 401)), self.assertRaisesMessage(HomeAssistantError, "401: Unauthorized"):
            fetch_home_assistant_registry()

    def test_template_error(self):
        with self.post(return_value=ha_response("TemplateSyntaxError: nope", 400)), self.assertRaisesMessage(HomeAssistantError, "TemplateSyntaxError"):
            fetch_home_assistant_registry()

    def test_unreadable_result(self):
        for text in ("not json", "[]", json.dumps({"areas": []}), json.dumps({"areas": [{}], "labels": [], "entities": []})):
            with self.subTest(text=text), self.post(return_value=ha_response(text)), self.assertRaises(HomeAssistantError):
                fetch_home_assistant_registry()


class HASyncTestCase(NSPMTestCase):
    def setUp(self):
        super().setUp()
        self.areas = LIVE_AREAS
        patcher = mock.patch("web.home_assistant_api.requests.post", side_effect=lambda *a, **k: ha_response(template_result(areas=self.areas)))
        self.post_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def ha_down(self, status=500, text="boom"):
        self.post_mock.side_effect = lambda *a, **k: ha_response(text, status)

    def link(self, room, area_id):
        room.home_assistant_link = Room.HomeAssistantLink.LINKED
        room.home_assistant_area_id = area_id
        room.save()


class AreasEndpointTests(HASyncTestCase):
    url = "/rest/v2/home_assistant/areas"

    def test_lists_areas_with_link_and_ignored(self):
        room = self.make_room("Kitchen")
        self.link(room, "kitchen")
        IgnoredHomeAssistantArea.objects.create(area_id="patio")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        by_id = {a["area_id"]: a for a in response.json()}
        self.assertEqual(len(by_id), len(LIVE_AREAS))
        self.assertEqual(by_id["kitchen"], {"area_id": "kitchen", "name": "Kitchen", "linked_room_id": room.id, "ignored": False})
        self.assertTrue(by_id["patio"]["ignored"])
        self.assertIsNone(by_id["patio"]["linked_room_id"])

    def test_ha_failure_is_a_502_with_the_message(self):
        self.ha_down(401, "401: Unauthorized")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 502)
        self.assertIn("401: Unauthorized", response.json()["detail"])

    def test_unreachable_is_a_502(self):
        self.post_mock.side_effect = requests.ConnectionError("refused")
        self.assertEqual(self.client.get(self.url).status_code, 502)


class RoomLinksGetTests(HASyncTestCase):
    url = "/rest/v2/home_assistant/room_links"

    def rows(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        return {r["name"]: r for r in response.json()}

    def test_suggestions_for_unset_rooms(self):
        for name in ("Kitchen", "Laundry", "Porch", "Oliver Bedroom", "Alex Bedroom", "Foyer", "Garden"):
            self.make_room(name)
        rows = self.rows()

        self.assertEqual(rows["Laundry"]["suggested_area_id"], "laundry_room")
        self.assertEqual(rows["Porch"]["suggested_area_id"], "front_porch")
        self.assertEqual(rows["Oliver Bedroom"]["suggested_area_id"], "olivers_bedroom")
        self.assertEqual(rows["Alex Bedroom"]["suggested_area_id"], "alexs_bedroom")
        self.assertEqual((rows["Kitchen"]["suggested_area_id"], rows["Kitchen"]["suggestion_ambiguous"]), ("kitchen", False))
        self.assertEqual((rows["Foyer"]["suggested_area_id"], rows["Foyer"]["suggestion_ambiguous"]), ("foyer", True))
        self.assertEqual(rows["Foyer"]["suggestion_candidates"], ["foyer", "front_foyer"])
        self.assertIsNone(rows["Garden"]["suggested_area_id"])
        self.assertEqual(rows["Garden"]["link"], "unset")

    def test_areas_linked_to_other_rooms_are_not_suggested(self):
        self.link(self.make_room("Foyer 2"), "foyer")
        self.make_room("Foyer")
        row = self.rows()["Foyer"]
        self.assertEqual((row["suggested_area_id"], row["suggestion_ambiguous"]), ("front_foyer", False))

    def test_linked_and_none_rooms_get_no_suggestion(self):
        self.link(self.make_room("Kitchen"), "kitchen")
        none = self.make_room("Patio")
        none.home_assistant_link = Room.HomeAssistantLink.NONE
        none.save()
        rows = self.rows()
        self.assertEqual((rows["Kitchen"]["area_name"], rows["Kitchen"]["area_missing"], rows["Kitchen"]["suggested_area_id"]), ("Kitchen", False, None))
        self.assertEqual((rows["Patio"]["link"], rows["Patio"]["suggested_area_id"], rows["Patio"]["area_name"]), ("none", None, None))

    def test_missing_area_is_flagged_not_reset(self):
        room = self.make_room("Old")
        self.link(room, "deleted_area")
        row = self.rows()["Old"]
        self.assertTrue(row["area_missing"])
        self.assertIsNone(row["area_name"])
        self.assertEqual((row["link"], row["area_id"]), ("linked", "deleted_area"))
        room.refresh_from_db()
        self.assertEqual((room.home_assistant_link, room.home_assistant_area_id), ("linked", "deleted_area"))

    def test_ha_failure_is_a_502(self):
        self.make_room("Kitchen")
        self.ha_down(500, "Internal Server Error")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 502)
        self.assertIn("500", response.json()["detail"])


class RoomLinksPutTests(HASyncTestCase):
    url = "/rest/v2/home_assistant/room_links"

    def test_links_and_marks_rooms(self):
        a, b, c = self.make_room("A"), self.make_room("B"), self.make_room("C")
        response = self.put_json(self.url, [{"room_id": a.id, "link": "linked", "area_id": "kitchen"}, {"room_id": b.id, "link": "none"}])

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), [{"room_id": a.id, "link": "linked", "area_id": "kitchen"}, {"room_id": b.id, "link": "none", "area_id": ""}])
        for room in (a, b, c):
            room.refresh_from_db()
        self.assertEqual((a.home_assistant_link, a.home_assistant_area_id), ("linked", "kitchen"))
        self.assertEqual(b.home_assistant_link, "none")
        self.assertEqual(c.home_assistant_link, "unset")

    def test_does_not_need_home_assistant(self):
        a = self.make_room("A")
        self.ha_down()
        self.assertEqual(self.put_json(self.url, [{"room_id": a.id, "link": "none"}]).status_code, 200)

    def test_unset_and_none_clear_the_area(self):
        a = self.make_room("A")
        self.link(a, "kitchen")
        self.put_json(self.url, [{"room_id": a.id, "link": "unset", "area_id": "kitchen"}])
        a.refresh_from_db()
        self.assertEqual((a.home_assistant_link, a.home_assistant_area_id), ("unset", ""))

    def test_duplicate_area_within_request_names_both_rooms(self):
        a, b = self.make_room("Alpha"), self.make_room("Beta")
        response = self.put_json(self.url, [{"room_id": a.id, "link": "linked", "area_id": "kitchen"}, {"room_id": b.id, "link": "linked", "area_id": "kitchen"}])
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertIn("Alpha", detail)
        self.assertIn("Beta", detail)
        a.refresh_from_db()
        self.assertEqual(a.home_assistant_link, "unset")

    def test_duplicate_of_a_room_outside_the_request_names_both_rooms(self):
        a, b = self.make_room("Alpha"), self.make_room("Beta")
        self.link(a, "kitchen")
        response = self.put_json(self.url, [{"room_id": b.id, "link": "linked", "area_id": "kitchen"}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("Alpha", response.json()["detail"])
        self.assertIn("Beta", response.json()["detail"])

    def test_swapping_areas_is_allowed(self):
        a, b = self.make_room("A"), self.make_room("B")
        self.link(a, "kitchen")
        self.link(b, "foyer")
        response = self.put_json(self.url, [{"room_id": a.id, "link": "linked", "area_id": "foyer"}, {"room_id": b.id, "link": "linked", "area_id": "kitchen"}])
        self.assertEqual(response.status_code, 200)

    def test_bad_entry_changes_nothing(self):
        a, b = self.make_room("A"), self.make_room("B")
        for body in (
            [{"room_id": a.id, "link": "linked", "area_id": "kitchen"}, {"room_id": 9999, "link": "none"}],
            [{"room_id": a.id, "link": "linked", "area_id": "kitchen"}, {"room_id": b.id, "link": "linked"}],
            [{"room_id": a.id, "link": "linked", "area_id": "kitchen"}, {"room_id": b.id, "link": "bogus"}],
            [{"room_id": a.id, "link": "linked", "area_id": "kitchen"}, {"room_id": a.id, "link": "none"}],
        ):
            with self.subTest(body=body):
                self.assertEqual(self.put_json(self.url, body).status_code, 400)
                a.refresh_from_db()
                self.assertEqual((a.home_assistant_link, a.home_assistant_area_id), ("unset", ""))

    def test_validation(self):
        a = self.make_room("A")
        for body in (
            {"room_id": a.id, "link": "linked"},
            {"room_id": a.id, "link": "linked", "area_id": "  "},
            {"room_id": a.id, "link": "none", "extra": 1},
            {"room_id": str(a.id), "link": "none"},
            {"room_id": a.id, "link": 1},
            {"link": "none"},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.put_json(self.url, [body]).status_code, 400)
        self.assertEqual(self.put_json(self.url, {"room_id": a.id}).status_code, 400)

    def test_does_not_reload_manager(self):
        a = self.make_room("A")
        self.put_json(self.url, [{"room_id": a.id, "link": "none"}])
        self.assertManagerNotReloaded()


class IgnoredAreasTests(HASyncTestCase):
    url = "/rest/v2/home_assistant/ignored_areas"

    def test_replaces_the_whole_set(self):
        IgnoredHomeAssistantArea.objects.create(area_id="old")
        IgnoredHomeAssistantArea.objects.create(area_id="keep")
        response = self.put_json(self.url, {"area_ids": ["keep", "patio", "patio"]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"area_ids": ["keep", "patio"]})
        self.assertEqual(set(IgnoredHomeAssistantArea.objects.values_list("area_id", flat=True)), {"keep", "patio"})

    def test_empty_clears(self):
        IgnoredHomeAssistantArea.objects.create(area_id="old")
        self.assertEqual(self.put_json(self.url, {"area_ids": []}).status_code, 200)
        self.assertFalse(IgnoredHomeAssistantArea.objects.exists())

    def test_validation_leaves_existing_rows(self):
        IgnoredHomeAssistantArea.objects.create(area_id="old")
        for body in ({"area_ids": ["a", ""]}, {"area_ids": [1]}, {"area_ids": "a"}, {"area_ids": [], "x": 1}, {}, ["a"]):
            with self.subTest(body=body):
                self.assertEqual(self.put_json(self.url, body).status_code, 400)
        self.assertEqual(IgnoredHomeAssistantArea.objects.count(), 1)

    def test_ignored_areas_show_in_the_areas_list(self):
        self.put_json(self.url, {"area_ids": ["patio"]})
        areas = {a["area_id"]: a for a in self.client.get("/rest/v2/home_assistant/areas").json()}
        self.assertTrue(areas["patio"]["ignored"])


class RoomsFromAreasTests(HASyncTestCase):
    url = "/rest/v2/home_assistant/rooms_from_areas"

    def test_creates_linked_rooms_with_pages_in_order(self):
        existing = self.make_room("Existing")
        existing.displayOrder = 7
        existing.save()
        IgnoredHomeAssistantArea.objects.create(area_id="patio")

        response = self.post_json(self.url, [{"area_id": "patio", "friendly_name": " Patio "}, {"area_id": "living_room", "friendly_name": "Lounge"}])

        self.assertEqual(response.status_code, 201, response.content)
        patio, lounge = Room.objects.get(friendly_name="Patio"), Room.objects.get(friendly_name="Lounge")
        self.assertEqual(response.json(), [{"room_id": patio.id, "area_id": "patio"}, {"room_id": lounge.id, "area_id": "living_room"}])
        self.assertEqual((patio.home_assistant_link, patio.home_assistant_area_id), ("linked", "patio"))
        self.assertEqual((patio.displayOrder, lounge.displayOrder), (8, 9))
        for room in (patio, lounge):
            self.assertEqual(RoomEntitiesPage.objects.filter(room=room, is_scenes_page=True).count(), 1)
            self.assertEqual(RoomEntitiesPage.objects.filter(room=room, is_scenes_page=False).count(), 1)
        self.assertFalse(IgnoredHomeAssistantArea.objects.filter(area_id="patio").exists())
        self.assertManagerReloaded(times=1)

    def test_name_length_limits(self):
        ok = self.post_json(self.url, [{"area_id": "patio", "friendly_name": "x" * 30}])
        self.assertEqual(ok.status_code, 201)
        for name in ("", "   ", "x" * 31):
            with self.subTest(name=name):
                self.assertEqual(self.post_json(self.url, [{"area_id": "kitchen", "friendly_name": name}]).status_code, 400)

    def test_one_bad_entry_creates_nothing(self):
        for body in (
            [{"area_id": "patio", "friendly_name": "Patio"}, {"area_id": "kitchen", "friendly_name": "x" * 31}],
            [{"area_id": "patio", "friendly_name": "Patio"}, {"area_id": "nowhere", "friendly_name": "Nowhere"}],
            [{"area_id": "patio", "friendly_name": "Patio"}, {"area_id": "patio", "friendly_name": "Again"}],
            [{"area_id": "patio", "friendly_name": "Patio"}, {"area_id": "kitchen", "friendly_name": "K", "extra": 1}],
            [],
        ):
            with self.subTest(body=body):
                self.assertEqual(self.post_json(self.url, body).status_code, 400)
        self.assertFalse(Room.objects.exists())
        self.assertFalse(RoomEntitiesPage.objects.exists())
        self.assertManagerNotReloaded()

    def test_already_linked_area_names_the_room(self):
        self.link(self.make_room("Patio Room"), "patio")
        response = self.post_json(self.url, [{"area_id": "patio", "friendly_name": "Patio"}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("Patio Room", response.json()["detail"])
        self.assertEqual(Room.objects.count(), 1)

    def test_failure_midway_rolls_back(self):
        with mock.patch("web.rest_v2.home_assistant_sync.create_entity_pages_for_room", side_effect=[None, RuntimeError("db")]):
            response = self.post_json(self.url, [{"area_id": "patio", "friendly_name": "Patio"}, {"area_id": "kitchen", "friendly_name": "Kitchen"}])
        self.assertEqual(response.status_code, 500)
        self.assertFalse(Room.objects.exists())
        self.assertManagerNotReloaded()

    def test_ha_failure_is_a_502_and_creates_nothing(self):
        self.ha_down(500, "boom")
        response = self.post_json(self.url, [{"area_id": "patio", "friendly_name": "Patio"}])
        self.assertEqual(response.status_code, 502)
        self.assertFalse(Room.objects.exists())

    def test_new_rooms_show_up_linked_in_room_links(self):
        self.post_json(self.url, [{"area_id": "patio", "friendly_name": "Patio"}])
        rows = self.client.get("/rest/v2/home_assistant/room_links").json()
        self.assertEqual([(r["name"], r["link"], r["area_name"]) for r in rows], [("Patio", "linked", "Patio")])


class RoomSerializerTests(NSPMTestCase):
    def url(self, room):
        return f"/rest/v2/rooms/{room.id}"

    def test_fields_are_in_the_representation(self):
        room = self.make_room("A")
        body = self.client.get(self.url(room)).json()
        self.assertEqual((body["home_assistant_link"], body["home_assistant_area_id"]), ("unset", ""))

    def test_patch_links_a_room(self):
        room = self.make_room("A")
        response = self.patch_json(self.url(room), {"home_assistant_link": "linked", "home_assistant_area_id": " kitchen "})
        self.assertEqual(response.status_code, 200, response.content)
        room.refresh_from_db()
        self.assertEqual((room.home_assistant_link, room.home_assistant_area_id), ("linked", "kitchen"))

    def test_linked_requires_an_area(self):
        room = self.make_room("A")
        for body in ({"home_assistant_link": "linked"}, {"home_assistant_link": "linked", "home_assistant_area_id": ""}):
            with self.subTest(body=body):
                response = self.patch_json(self.url(room), body)
                self.assertEqual(response.status_code, 400)
                self.assertIn("home_assistant_area_id", response.json()["message"])

    def test_area_must_be_unique(self):
        a, b = self.make_room("Alpha"), self.make_room("Beta")
        a.home_assistant_link, a.home_assistant_area_id = "linked", "kitchen"
        a.save()
        response = self.patch_json(self.url(b), {"home_assistant_link": "linked", "home_assistant_area_id": "kitchen"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Alpha", response.json()["message"])
        # Re-sending a room's own area is fine.
        self.assertEqual(self.patch_json(self.url(a), {"home_assistant_link": "linked", "home_assistant_area_id": "kitchen"}).status_code, 200)

    def test_unset_and_none_clear_the_area(self):
        for link in ("unset", "none"):
            with self.subTest(link=link):
                room = self.make_room("A")
                room.home_assistant_link, room.home_assistant_area_id = "linked", "kitchen"
                room.save()
                response = self.patch_json(self.url(room), {"home_assistant_link": link, "home_assistant_area_id": "kitchen"})
                self.assertEqual(response.status_code, 200)
                room.refresh_from_db()
                self.assertEqual((room.home_assistant_link, room.home_assistant_area_id), (link, ""))

    def test_patch_name_alone_keeps_the_link(self):
        room = self.make_room("A")
        room.home_assistant_link, room.home_assistant_area_id = "linked", "kitchen"
        room.save()
        self.patch_json(self.url(room), {"friendly_name": "B"})
        room.refresh_from_db()
        self.assertEqual((room.friendly_name, room.home_assistant_link, room.home_assistant_area_id), ("B", "linked", "kitchen"))

    def test_invalid_values(self):
        room = self.make_room("A")
        for body in ({"home_assistant_link": "maybe"}, {"home_assistant_link": 1}, {"home_assistant_area_id": 5}, {"home_assistant_area_id": "x" * 256}):
            with self.subTest(body=body):
                self.assertEqual(self.patch_json(self.url(room), body).status_code, 400)

    def test_create_room_defaults_to_unset(self):
        response = self.post_json("/rest/v2/rooms", {"friendly_name": "New"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["home_assistant_link"], "unset")

    def test_create_linked_room(self):
        response = self.post_json("/rest/v2/rooms", {"friendly_name": "New", "home_assistant_link": "linked", "home_assistant_area_id": "kitchen"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.post_json("/rest/v2/rooms", {"friendly_name": "Dup", "home_assistant_link": "linked", "home_assistant_area_id": "kitchen"}).status_code, 400)


class MigrationDefaultTests(TransactionTestCase):
    def test_existing_rooms_are_unset(self):
        executor = MigrationExecutor(connection)
        before = [("web", "0073_tftupload")]
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        old_room = old_apps.get_model("web", "Room")
        room_id = old_room.objects.create(friendly_name="Legacy").id

        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        room = executor.loader.project_state(executor.loader.graph.leaf_nodes()).apps.get_model("web", "Room").objects.get(id=room_id)
        self.assertEqual((room.home_assistant_link, room.home_assistant_area_id), ("unset", ""))
