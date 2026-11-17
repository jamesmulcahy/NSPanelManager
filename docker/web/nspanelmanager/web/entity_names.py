"""Turning a Home Assistant friendly name into an NSPM entity name."""

import re

# Characters that may sit between the room name and the rest of the name.
_SEPARATORS = r"[\s\-:]+"
_APOSTROPHES = "'’ʼ`"
# An optional possessive after a word: "Oliver’s", "Oliver's".
_POSSESSIVE = rf"(?:[{_APOSTROPHES}]s)?"


def _room_pattern(room_name):
    """A regex matching room_name at the start of a name, ignoring case, ’s and spacing."""
    # Drop possessives from the room name itself ("Oliver’s Bedroom" -> "Oliver Bedroom"), then allow them back anywhere.
    cleaned = re.sub(rf"[{_APOSTROPHES}]s\b", "", room_name, flags=re.IGNORECASE)
    words = cleaned.split()
    if not words:
        return None
    body = r"\s+".join(re.escape(word) + _POSSESSIVE for word in words)
    return re.compile(rf"^\s*{body}(?=$|{_SEPARATORS})", re.IGNORECASE)


def suggest_entity_name(friendly_name, room_names, max_length=255):
    """The name to offer for an imported entity: friendly_name without the room name in front.

    room_names are the names to try removing (the NSPM room name and the HA area name).
    The longest name that matches wins. Matching ignores case and ’s / 's, and the name
    must be followed by a space, "-" or ":" (so "Kitchenette" is not stripped for "Kitchen").
    If stripping would leave nothing, the full name is kept. The result is trimmed and cut
    to max_length (the Entity.friendly_name column size).
    """
    name = (friendly_name or "").strip()
    result = name
    for room_name in sorted((n for n in room_names if n and n.strip()), key=lambda n: len(n.strip()), reverse=True):
        pattern = _room_pattern(room_name.strip())
        if pattern is None:
            continue
        match = pattern.match(name)
        if not match:
            continue
        remainder = re.sub(rf"^{_SEPARATORS}", "", name[match.end() :]).strip()
        if remainder:
            result = remainder
            break
        # The whole name is the room name: keep it as is.
        break
    return result[:max_length].rstrip()
