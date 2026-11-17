from django.test import SimpleTestCase

from web.entity_names import suggest_entity_name


class SuggestEntityNameTests(SimpleTestCase):
    def test_cases(self):
        cases = [
            ("Kitchen Island Light", ["Kitchen"], "Island Light"),
            ("kitchen island light", ["KITCHEN"], "island light"),
            ("Kitchen - Island Light", ["Kitchen"], "Island Light"),
            ("Kitchen: Island Light", ["Kitchen"], "Island Light"),
            ("Kitchen:Island", ["Kitchen"], "Island"),
            ("Kitchen   Island", ["Kitchen"], "Island"),
            ("Oliver’s Bedroom Main Lights", ["Oliver Bedroom", "Oliver’s Bedroom"], "Main Lights"),
            ("Oliver's Bedroom Main Lights", ["Oliver’s Bedroom"], "Main Lights"),
            ("Oliver’s Bedroom Main Lights", ["Oliver Bedroom"], "Main Lights"),
            ("Alex's Lamp", ["Alex"], "Lamp"),
            ("Alexs Lamp", ["Alex"], "Alexs Lamp"),  # no apostrophe: a different word
            ("Laundry Room Main Lights", ["Laundry", "Laundry Room"], "Main Lights"),  # longest wins
            ("Laundry Room Main Lights", ["Laundry Room", "Laundry"], "Main Lights"),
            ("Kitchenette Light", ["Kitchen"], "Kitchenette Light"),  # word boundary
            ("Island Kitchen Light", ["Kitchen"], "Island Kitchen Light"),  # only at the start
            ("Kitchen", ["Kitchen"], "Kitchen"),  # nothing left: keep
            ("Kitchen -", ["Kitchen"], "Kitchen -"),
            ("Kitchen’s", ["Kitchen"], "Kitchen’s"),
            ("Garage Main Lights", [], "Garage Main Lights"),
            ("Garage Main Lights", ["", None, "  "], "Garage Main Lights"),
            ("  Kitchen Island  ", ["Kitchen"], "Island"),
            ("Master Bedroom Ceiling Fan Light", ["Master Bedroom"], "Ceiling Fan Light"),
            ("Living Room", ["Living", "Living Room"], "Living Room"),  # longest match leaves nothing
            ("Front Porch Overhead Light", ["Porch", "Front Porch"], "Overhead Light"),
            ("Porch Light", ["Porch", "Front Porch"], "Light"),
            ("Room (1) Light", ["Room (1)"], "Light"),  # regex characters are literal
            ("", ["Kitchen"], ""),
            (None, ["Kitchen"], ""),
        ]
        for friendly_name, rooms, expected in cases:
            with self.subTest(friendly_name=friendly_name, rooms=rooms):
                self.assertEqual(suggest_entity_name(friendly_name, rooms), expected)

    def test_max_length(self):
        self.assertEqual(suggest_entity_name("Kitchen " + "x" * 20, ["Kitchen"], max_length=10), "x" * 10)

    def test_max_length_trims_trailing_space(self):
        self.assertEqual(suggest_entity_name("Kitchen abcd efgh", ["Kitchen"], max_length=5), "abcd")

    def test_default_max_length_is_entity_column_size(self):
        self.assertEqual(len(suggest_entity_name("y" * 400, [])), 255)
