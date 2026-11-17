"""
Where to put new entities in a room: fill free slots first, then add pages (D4 of HA_SYNC_PLAN.md).

plan_placement is pure; apply_placement writes the plan to the database and must be called
inside the caller's transaction.
"""

from dataclasses import dataclass, field

from .models import Entity, RoomEntitiesPage, Scene

PAGE_SIZES = (4, 8, 12)
DEFAULT_PAGE_SIZE = 8


@dataclass(frozen=True)
class PageSlots:
    """An existing entity page: its id, size and the positions already in use."""

    id: int
    page_type: int
    occupied: frozenset = frozenset()


@dataclass(frozen=True)
class SlotAssignment:
    """One placed item. Exactly one of page_id (existing page) and new_page_index (index into Plan.new_page_sizes) is set."""

    position: int
    page_id: int = None
    new_page_index: int = None


@dataclass(frozen=True)
class Plan:
    assignments: list = field(default_factory=list)  # One SlotAssignment per item, in item order
    new_page_sizes: list = field(default_factory=list)  # Sizes of the pages to create, in display order


def new_page_sizes_for(count, last_page_size):
    """Sizes of the pages to add for count items that did not fit: one page of last_page_size if it holds them, else the smallest that does, with 12s first for large counts."""
    sizes = []
    remaining = count
    while remaining > PAGE_SIZES[-1]:
        sizes.append(PAGE_SIZES[-1])
        remaining -= PAGE_SIZES[-1]
    if remaining > 0:
        sizes.append(last_page_size if remaining <= last_page_size else min(size for size in PAGE_SIZES if size >= remaining))
    return sizes


def plan_placement(pages, count):
    """Plan slots for count new items in a room.

    pages: the room's entity pages (not scene pages) as PageSlots, ordered by display_order.
    Free slots on those pages are used first, in page then slot order. The rest go on new
    pages sized by new_page_sizes_for, where the "last page size" is the size of the room's
    last entity page (8 when it has none).
    """
    assignments = []
    for page in pages:
        for position in range(page.page_type):
            if len(assignments) == count:
                break
            if position not in page.occupied:
                assignments.append(SlotAssignment(position=position, page_id=page.id))
    remaining = count - len(assignments)
    last_size = pages[-1].page_type if pages else DEFAULT_PAGE_SIZE
    sizes = new_page_sizes_for(remaining, last_size)
    for index, size in enumerate(sizes):
        for position in range(size):
            if len(assignments) == count:
                break
            assignments.append(SlotAssignment(position=position, new_page_index=index))
    return Plan(assignments=assignments, new_page_sizes=sizes)


def load_room_pages(room):
    """The room's entity pages as PageSlots, ordered by display_order (scene pages excluded). Slots held by entities or scenes count as occupied."""
    pages = RoomEntitiesPage.objects.filter(room=room, is_scenes_page=False).order_by("display_order", "id")
    result = []
    for page in pages:
        occupied = set(Entity.objects.filter(entities_page=page).values_list("room_view_position", flat=True))
        occupied |= set(Scene.objects.filter(entities_page=page).values_list("room_view_position", flat=True))
        result.append(PageSlots(id=page.id, page_type=page.page_type, occupied=frozenset(occupied)))
    return result


def apply_placement(room, plan):
    """Create the plan's new pages after the room's existing ones and resolve the assignments.

    Returns a list of (RoomEntitiesPage, position), one per assignment in plan order. Run it inside
    the caller's transaction; it does not open one or reload the manager.
    """
    last = RoomEntitiesPage.objects.filter(room=room).order_by("-display_order", "-id").first()
    next_order = last.display_order + 1 if last else 0
    created = []
    for offset, size in enumerate(plan.new_page_sizes):
        created.append(RoomEntitiesPage.objects.create(room=room, display_order=next_order + offset, page_type=size, is_scenes_page=False))
    existing = {}
    if any(a.page_id is not None for a in plan.assignments):
        existing = RoomEntitiesPage.objects.in_bulk({a.page_id for a in plan.assignments if a.page_id is not None})
    resolved = []
    for assignment in plan.assignments:
        page = existing[assignment.page_id] if assignment.page_id is not None else created[assignment.new_page_index]
        resolved.append((page, assignment.position))
    return resolved


def place_in_room(room, count):
    """plan_placement against the room's current pages, then apply_placement. Returns (resolved, new_pages_count)."""
    plan = plan_placement(load_room_pages(room), count)
    return apply_placement(room, plan), len(plan.new_page_sizes)
