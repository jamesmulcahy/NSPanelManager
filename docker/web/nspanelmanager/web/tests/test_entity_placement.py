from django.test import SimpleTestCase

from web.entity_placement import (
    PageSlots,
    apply_placement,
    load_room_pages,
    new_page_sizes_for,
    place_in_room,
    plan_placement,
)
from web.models import Entity, RoomEntitiesPage

from .harness import NSPMTestCase


def page(id, size, occupied=()):
    return PageSlots(id=id, page_type=size, occupied=frozenset(occupied))


class NewPageSizeTests(SimpleTestCase):
    def test_table(self):
        cases = [
            # (count, last page size, expected new pages)
            (0, 4, []),
            (1, 4, [4]),
            (3, 4, [4]),
            (4, 4, [4]),
            (5, 4, [8]),
            (6, 4, [8]),
            (9, 4, [12]),
            (12, 4, [12]),
            (13, 4, [12, 4]),
            (15, 4, [12, 4]),
            (16, 4, [12, 4]),
            (17, 4, [12, 8]),
            (24, 4, [12, 12]),
            (25, 4, [12, 12, 4]),
            (1, 8, [8]),
            (8, 8, [8]),
            (9, 8, [12]),
            (15, 8, [12, 8]),
            (1, 12, [12]),
            (12, 12, [12]),
            (13, 12, [12, 12]),
            (30, 12, [12, 12, 12]),
        ]
        for count, last, expected in cases:
            with self.subTest(count=count, last=last):
                self.assertEqual(new_page_sizes_for(count, last), expected)


class PlanPlacementTests(SimpleTestCase):
    def test_no_pages_uses_size_8(self):
        plan = plan_placement([], 3)
        self.assertEqual(plan.new_page_sizes, [8])
        self.assertEqual([(a.new_page_index, a.position) for a in plan.assignments], [(0, 0), (0, 1), (0, 2)])

    def test_no_pages_large(self):
        self.assertEqual(plan_placement([], 10).new_page_sizes, [12])

    def test_zero_items(self):
        plan = plan_placement([page(1, 4)], 0)
        self.assertEqual((plan.assignments, plan.new_page_sizes), ([], []))

    def test_fills_free_slots_in_page_then_slot_order(self):
        pages = [page(1, 4, {0, 2}), page(2, 8, {0})]
        plan = plan_placement(pages, 4)
        self.assertEqual([(a.page_id, a.position) for a in plan.assignments], [(1, 1), (1, 3), (2, 1), (2, 2)])
        self.assertEqual(plan.new_page_sizes, [])

    def test_overflow_after_filling_uses_last_page_size(self):
        pages = [page(1, 4, {0, 1}), page(2, 4, {0})]  # 5 free slots
        plan = plan_placement(pages, 8)  # 5 fit, 3 left, S=4
        self.assertEqual(plan.new_page_sizes, [4])
        self.assertEqual([a.page_id for a in plan.assignments], [1, 1, 2, 2, 2, None, None, None])
        self.assertEqual([a.new_page_index for a in plan.assignments][5:], [0, 0, 0])
        self.assertEqual([a.position for a in plan.assignments][5:], [0, 1, 2])

    def test_full_last_page_s4(self):
        pages = [page(1, 4, {0, 1, 2, 3})]
        for count, sizes in ((3, [4]), (6, [8]), (15, [12, 4])):
            with self.subTest(count=count):
                self.assertEqual(plan_placement(pages, count).new_page_sizes, sizes)

    def test_new_pages_are_filled_in_order(self):
        plan = plan_placement([page(1, 4, {0, 1, 2, 3})], 15)
        self.assertEqual(plan.new_page_sizes, [12, 4])
        in_new = [(a.new_page_index, a.position) for a in plan.assignments]
        self.assertEqual(in_new[:12], [(0, i) for i in range(12)])
        self.assertEqual(in_new[12:], [(1, 0), (1, 1), (1, 2)])

    def test_last_page_size_is_from_the_last_page_even_if_it_has_room(self):
        # The earlier page is 12, the last is 4. Remaining N is based on the last page (S=4).
        pages = [page(1, 12, set(range(12))), page(2, 4, {0, 1, 2})]
        plan = plan_placement(pages, 3)  # one free slot, then 2 left, S=4
        self.assertEqual(plan.new_page_sizes, [4])

    def test_exact_fit_adds_no_pages(self):
        plan = plan_placement([page(1, 4)], 4)
        self.assertEqual(plan.new_page_sizes, [])
        self.assertEqual(len(plan.assignments), 4)


class ApplyPlacementTests(NSPMTestCase):
    def setUp(self):
        super().setUp()
        self.room = self.make_room("Office")

    def entity_pages(self):
        return list(RoomEntitiesPage.objects.filter(room=self.room, is_scenes_page=False).order_by("display_order", "id"))

    def test_load_room_pages_excludes_scene_pages_and_reports_occupied_slots(self):
        first = self.entities_page(self.room)
        self.make_light(self.room, "A", page=first, slot=1)
        self.make_scene(self.room, "S", page=first, slot=3)
        pages = load_room_pages(self.room)
        self.assertEqual(len(pages), 1)
        self.assertEqual((pages[0].id, pages[0].page_type, pages[0].occupied), (first.id, 4, frozenset({1, 3})))

    def test_load_room_pages_orders_by_display_order(self):
        extra = RoomEntitiesPage.objects.create(room=self.room, display_order=5, page_type=8)
        middle = RoomEntitiesPage.objects.create(room=self.room, display_order=2, page_type=12)
        ids = [p.id for p in load_room_pages(self.room)]
        self.assertEqual(ids, [self.entities_page(self.room).id, middle.id, extra.id])

    def test_fills_existing_then_adds_pages_after_existing_ones(self):
        first = self.entities_page(self.room)
        self.make_light(self.room, "A", page=first, slot=0)
        resolved, added = place_in_room(self.room, 6)  # 3 free, 3 left, S=4
        self.assertEqual(added, 1)
        self.assertEqual([(p.id, pos) for p, pos in resolved[:3]], [(first.id, 1), (first.id, 2), (first.id, 3)])
        new_page = self.entity_pages()[-1]
        self.assertNotEqual(new_page.id, first.id)
        self.assertEqual((new_page.page_type, new_page.is_scenes_page, new_page.room_id), (4, False, self.room.id))
        self.assertEqual([(p.id, pos) for p, pos in resolved[3:]], [(new_page.id, 0), (new_page.id, 1), (new_page.id, 2)])

    def test_display_order_continues_after_all_room_pages(self):
        # make_room gives the entity page and the scene page display_order 0.
        place_in_room(self.room, 4 + 15)  # 4 free; then 15 -> [12, 4]
        orders = [(p.display_order, p.page_type) for p in self.entity_pages()]
        self.assertEqual(orders, [(0, 4), (1, 12), (2, 4)])

    def test_scene_pages_are_not_filled(self):
        scenes = self.scenes_page(self.room)
        first = self.entities_page(self.room)
        for slot in range(4):
            self.make_light(self.room, f"L{slot}", page=first, slot=slot)
        resolved, added = place_in_room(self.room, 2)
        self.assertNotIn(scenes.id, [p.id for p, _ in resolved])
        self.assertEqual(added, 1)

    def test_room_with_no_entity_pages_gets_size_8(self):
        RoomEntitiesPage.objects.filter(room=self.room, is_scenes_page=False).delete()
        resolved, added = place_in_room(self.room, 2)
        self.assertEqual(added, 1)
        page = resolved[0][0]
        self.assertEqual((page.page_type, page.display_order), (8, 1))  # after the scene page at 0

    def test_placed_slots_accept_entities(self):
        resolved, _ = place_in_room(self.room, 7)
        for index, (page, position) in enumerate(resolved):
            Entity.objects.create(room=self.room, friendly_name=f"E{index}", entity_type="light", entities_page=page, room_view_position=position, entity_data={})
        self.assertEqual(len({(p.id, pos) for p, pos in resolved}), 7)
        # Everything is now placed: the next one needs a new page or a free slot, never an occupied one.
        resolved2, _ = place_in_room(self.room, 1)
        self.assertEqual(Entity.objects.filter(entities_page=resolved2[0][0], room_view_position=resolved2[0][1]).count(), 0)

    def test_apply_placement_does_not_reload_the_manager(self):
        apply_placement(self.room, plan_placement(load_room_pages(self.room), 9))
        self.assertManagerNotReloaded()
