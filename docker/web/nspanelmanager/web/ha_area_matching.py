"""Suggesting a Home Assistant area for an NSPM room, by name."""

import re
from dataclasses import dataclass, field


def normalise_name(name):
    """Lowercase; drop apostrophes (and the "s" of a possessive: "Oliver's Bedroom" -> "oliver bedroom"); collapse whitespace."""
    name = name.lower()
    name = re.sub(r"['’‘ʼ]s\b", "", name)
    name = re.sub(r"['’‘ʼ]", "", name)
    return " ".join(name.split())


@dataclass
class AreaSuggestion:
    # The area to preselect, or None when there is no single clear answer.
    area_id: str | None = None
    # More than one area could be meant. Either nothing is suggested (several exact or several prefix/suffix
    # matches) or an exact match is suggested while another candidate exists (Foyer vs. Front Foyer).
    ambiguous: bool = False
    # Every area that matched, exact matches first.
    candidates: list[str] = field(default_factory=list)


def suggest_area(room_name, areas):
    """Suggest one of areas ([{"area_id", "name"}]) for a room called room_name.

    1. An exact normalised match wins. If another area also matches by prefix/suffix (Foyer -> Foyer and Front Foyer)
       the exact match is still suggested, but flagged as ambiguous so the UI can show the alternatives.
       Several exact matches suggest nothing.
    2. Otherwise a unique prefix or suffix match on whole words (Laundry -> Laundry Room, Porch -> Front Porch).
       Several of those suggest nothing.
    3. Otherwise no suggestion.
    """
    room = normalise_name(room_name)
    if not room:
        return AreaSuggestion()

    exact, partial = [], []
    for area in areas:
        name = normalise_name(area["name"])
        if name == room:
            exact.append(area["area_id"])
        elif name.startswith(room + " ") or name.endswith(" " + room):
            partial.append(area["area_id"])

    candidates = exact + partial
    if len(exact) == 1:
        return AreaSuggestion(area_id=exact[0], ambiguous=bool(partial), candidates=candidates)
    if len(exact) > 1:
        return AreaSuggestion(ambiguous=True, candidates=candidates)
    if len(partial) == 1:
        return AreaSuggestion(area_id=partial[0], candidates=candidates)
    if len(partial) > 1:
        return AreaSuggestion(ambiguous=True, candidates=candidates)
    return AreaSuggestion()
