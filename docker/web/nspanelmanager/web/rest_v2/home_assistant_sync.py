"""Linking NSPM rooms to Home Assistant areas, and making rooms from areas (/rest/v2/home_assistant/...)."""

import logging

from django.db import transaction
from django.db.models import Max
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from web.apps import send_mqttmanager_reload_command
from web.entity_data import NSPM_TYPE_BY_HA_DOMAIN, build_entity_data_from_state, is_light_group, ha_domain
from web.entity_names import suggest_entity_name
from web.entity_placement import place_in_room
from web.ha_area_matching import suggest_area
from web.home_assistant_api import HomeAssistantError, fetch_home_assistant_registry
from web.models import Entity, IgnoredHomeAssistantArea, Room, Settings

from .rooms import StrictCharField, StrictChoiceField, StrictIntegerField, TrimmedCharField, create_entity_pages_for_room
from .schema import extend_schema

logger = logging.getLogger(__name__)

_FRIENDLY_NAME_MAX = Room._meta.get_field("friendly_name").max_length
_ENTITY_NAME_MAX = Entity._meta.get_field("friendly_name").max_length
_ENTITY_ID_MAX = 255
_AREA_ID_MAX = Room._meta.get_field("home_assistant_area_id").max_length


class HomeAssistantUnavailable(APIException):
    """Home Assistant could not be reached or refused the request; detail is HA's own message."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Home Assistant is unavailable."
    default_code = "home_assistant_unavailable"


class SyncBadRequest(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Invalid request."
    default_code = "invalid"


def fetch_registry_or_502():
    """fetch_home_assistant_registry(), with its failures turned into a 502 whose detail is the message."""
    try:
        return fetch_home_assistant_registry()
    except HomeAssistantError as e:
        raise HomeAssistantUnavailable(str(e)) from e


class HomeAssistantDetailSerializer(serializers.Serializer):
    """DRF's error body for a request it rejects, e.g. a 502 from Home Assistant or a 400 for a duplicate area."""

    detail = serializers.CharField()


class ValidationErrorSerializer(serializers.Serializer):
    """A 400 for a malformed body: {"detail": message}, or messages by field (one object per list item)."""

    detail = serializers.CharField(required=False)
    non_field_errors = serializers.ListField(child=serializers.CharField(), required=False)


class StrictSerializer(serializers.Serializer):
    """Unknown request fields are a 400."""

    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = {key: ["Unknown field."] for key in data if key not in self.fields}
            if unknown:
                raise serializers.ValidationError(unknown)
        return super().to_internal_value(data)


_ERRORS = {400: ValidationErrorSerializer, 403: HomeAssistantDetailSerializer, 415: HomeAssistantDetailSerializer}
_HA_ERRORS = {**_ERRORS, 502: HomeAssistantDetailSerializer}


# ---------------------------------------------------------------------------------------------- areas


class HomeAssistantAreaSerializer(serializers.Serializer):
    area_id = serializers.CharField()
    name = serializers.CharField()
    linked_room_id = serializers.IntegerField(allow_null=True, help_text="The room linked to this area, if any.")
    ignored = serializers.BooleanField(help_text="The user asked not to be offered this area as a new room.")


class AreasView(APIView):
    http_method_names = ["get", "head"]

    @extend_schema(responses={200: HomeAssistantAreaSerializer(many=True), 502: HomeAssistantDetailSerializer}, operation_id="list_home_assistant_areas")
    def get(self, request):
        registry = fetch_registry_or_502()
        linked = {r.home_assistant_area_id: r.id for r in Room.objects.filter(home_assistant_link=Room.HomeAssistantLink.LINKED).order_by("displayOrder", "id")}
        ignored = set(IgnoredHomeAssistantArea.objects.values_list("area_id", flat=True))
        areas = [{"area_id": a["area_id"], "name": a["name"], "linked_room_id": linked.get(a["area_id"]), "ignored": a["area_id"] in ignored} for a in registry["areas"]]
        areas.sort(key=lambda a: a["name"].lower())
        return Response(HomeAssistantAreaSerializer(areas, many=True).data)


# ---------------------------------------------------------------------------------------------- room links


class RoomLinkSerializer(serializers.Serializer):
    room_id = serializers.IntegerField()
    name = serializers.CharField()
    link = serializers.ChoiceField(choices=Room.HomeAssistantLink.choices)
    area_id = serializers.CharField(help_text="Empty unless the room is linked.")
    area_name = serializers.CharField(allow_null=True, help_text="The linked area's current name; null when not linked or the area no longer exists.")
    area_missing = serializers.BooleanField(help_text="The room is linked to an area Home Assistant no longer has. It is kept linked, never reset.")
    suggested_area_id = serializers.CharField(allow_null=True, help_text="For an unset room: the area its name matches, if there is a clear one.")
    suggestion_ambiguous = serializers.BooleanField(help_text="More than one area could match; see suggestion_candidates.")
    suggestion_candidates = serializers.ListField(child=serializers.CharField(), help_text="Every area that matched the room's name, best first.")


class RoomLinkUpdateSerializer(StrictSerializer):
    room_id = StrictIntegerField()
    link = StrictChoiceField(choices=Room.HomeAssistantLink.choices)
    area_id = TrimmedCharField(allow_blank=True, max_length=_AREA_ID_MAX, required=False, help_text="Required when link is linked; ignored (stored empty) otherwise.")

    def validate(self, attrs):
        if attrs["link"] == Room.HomeAssistantLink.LINKED:
            if not attrs.get("area_id"):
                raise serializers.ValidationError({"area_id": ["Required when link is linked."]})
        else:
            attrs["area_id"] = ""
        return attrs


class RoomLinkResultSerializer(serializers.Serializer):
    room_id = serializers.IntegerField()
    link = serializers.ChoiceField(choices=Room.HomeAssistantLink.choices)
    area_id = serializers.CharField()


def _duplicate_area_message(area_id, first, second):
    return f'Home Assistant area "{area_id}" can only be linked to one room, but it is assigned to both "{first.friendly_name}" (id {first.id}) and "{second.friendly_name}" (id {second.id}).'


class RoomLinksView(APIView):
    http_method_names = ["get", "put", "head"]

    @extend_schema(responses={200: RoomLinkSerializer(many=True), 502: HomeAssistantDetailSerializer}, operation_id="list_room_links")
    def get(self, request):
        registry = fetch_registry_or_502()
        area_names = {a["area_id"]: a["name"] for a in registry["areas"]}
        rooms = list(Room.objects.order_by("displayOrder", "id"))
        taken = {r.home_assistant_area_id for r in rooms if r.home_assistant_link == Room.HomeAssistantLink.LINKED}
        free_areas = [a for a in registry["areas"] if a["area_id"] not in taken]

        rows = []
        for room in rooms:
            linked = room.home_assistant_link == Room.HomeAssistantLink.LINKED
            suggestion = suggest_area(room.friendly_name, free_areas) if room.home_assistant_link == Room.HomeAssistantLink.UNSET else None
            rows.append(
                {
                    "room_id": room.id,
                    "name": room.friendly_name,
                    "link": room.home_assistant_link,
                    "area_id": room.home_assistant_area_id,
                    "area_name": area_names.get(room.home_assistant_area_id) if linked else None,
                    "area_missing": linked and room.home_assistant_area_id not in area_names,
                    "suggested_area_id": suggestion.area_id if suggestion else None,
                    "suggestion_ambiguous": suggestion.ambiguous if suggestion else False,
                    "suggestion_candidates": suggestion.candidates if suggestion else [],
                }
            )
        return Response(RoomLinkSerializer(rows, many=True).data)

    @extend_schema(request=RoomLinkUpdateSerializer(many=True), responses={200: RoomLinkResultSerializer(many=True), **_ERRORS}, operation_id="update_room_links")
    def put(self, request):
        serializer = RoomLinkUpdateSerializer(data=request.data, many=True, allow_empty=True)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data

        ids = [item["room_id"] for item in items]
        if len(ids) != len(set(ids)):
            raise SyncBadRequest("Duplicate room ids in request.")

        with transaction.atomic():
            rooms = {r.id: r for r in Room.objects.select_for_update().all()}
            unknown = sorted(set(ids) - set(rooms))
            if unknown:
                raise SyncBadRequest(f"Unknown room ids: {unknown}")

            for item in items:
                room = rooms[item["room_id"]]
                room.home_assistant_link = item["link"]
                room.home_assistant_area_id = item["area_id"]

            # Check the final state of every room, not just the ones in the request.
            owner = {}
            for room in sorted(rooms.values(), key=lambda r: r.id):
                if room.home_assistant_link != Room.HomeAssistantLink.LINKED:
                    continue
                if room.home_assistant_area_id in owner:
                    raise SyncBadRequest(_duplicate_area_message(room.home_assistant_area_id, owner[room.home_assistant_area_id], room))
                owner[room.home_assistant_area_id] = room

            Room.objects.bulk_update([rooms[i] for i in ids], ["home_assistant_link", "home_assistant_area_id"])

        logger.info("Home Assistant room links updated for room ids: %s", sorted(ids))
        result = [{"room_id": i, "link": rooms[i].home_assistant_link, "area_id": rooms[i].home_assistant_area_id} for i in ids]
        return Response(RoomLinkResultSerializer(result, many=True).data)


# ---------------------------------------------------------------------------------------------- ignored areas


class IgnoredAreasSerializer(StrictSerializer):
    area_ids = serializers.ListField(child=StrictCharField(max_length=_AREA_ID_MAX, allow_blank=False), help_text="The complete set of ignored areas; anything not listed stops being ignored.")


class IgnoredAreasView(APIView):
    http_method_names = ["put", "head"]

    @extend_schema(request=IgnoredAreasSerializer, responses={200: IgnoredAreasSerializer, **_ERRORS}, operation_id="set_ignored_home_assistant_areas")
    def put(self, request):
        serializer = IgnoredAreasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wanted = list(dict.fromkeys(serializer.validated_data["area_ids"]))

        with transaction.atomic():
            IgnoredHomeAssistantArea.objects.exclude(area_id__in=wanted).delete()
            existing = set(IgnoredHomeAssistantArea.objects.values_list("area_id", flat=True))
            IgnoredHomeAssistantArea.objects.bulk_create([IgnoredHomeAssistantArea(area_id=a) for a in wanted if a not in existing])

        return Response({"area_ids": wanted})


# ---------------------------------------------------------------------------------------------- rooms from areas


class RoomFromAreaSerializer(StrictSerializer):
    area_id = StrictCharField(max_length=_AREA_ID_MAX, allow_blank=False)
    friendly_name = TrimmedCharField(allow_blank=False, max_length=_FRIENDLY_NAME_MAX, help_text="Leading and trailing whitespace is removed.")


class CreatedRoomSerializer(serializers.Serializer):
    room_id = serializers.IntegerField()
    area_id = serializers.CharField()


class RoomsFromAreasView(APIView):
    http_method_names = ["post", "head"]

    @extend_schema(request=RoomFromAreaSerializer(many=True), responses={201: CreatedRoomSerializer(many=True), **_HA_ERRORS}, operation_id="create_rooms_from_home_assistant_areas")
    def post(self, request):
        serializer = RoomFromAreaSerializer(data=request.data, many=True, allow_empty=False)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data

        area_ids = [item["area_id"] for item in items]
        if len(area_ids) != len(set(area_ids)):
            raise SyncBadRequest("Duplicate area ids in request.")

        known = {a["area_id"] for a in fetch_registry_or_502()["areas"]}
        missing = [a for a in area_ids if a not in known]
        if missing:
            raise SyncBadRequest(f"Areas not found in Home Assistant: {missing}")

        created = []
        with transaction.atomic():
            taken = {r.home_assistant_area_id: r for r in Room.objects.filter(home_assistant_link=Room.HomeAssistantLink.LINKED)}
            for item in items:
                if item["area_id"] in taken:
                    other = taken[item["area_id"]]
                    raise SyncBadRequest(f'Home Assistant area "{item["area_id"]}" is already linked to the room "{other.friendly_name}" (id {other.id}).')

            next_order = (Room.objects.aggregate(m=Max("displayOrder"))["m"] or 0) + 1
            for offset, item in enumerate(items):
                room = Room.objects.create(
                    friendly_name=item["friendly_name"],
                    displayOrder=next_order + offset,
                    home_assistant_link=Room.HomeAssistantLink.LINKED,
                    home_assistant_area_id=item["area_id"],
                )
                create_entity_pages_for_room(room)
                created.append({"room_id": room.id, "area_id": item["area_id"]})
            # A new room replaces the "don't ask again" decision for its area.
            IgnoredHomeAssistantArea.objects.filter(area_id__in=area_ids).delete()

        logger.info("Rooms created from Home Assistant areas: %s", created)
        send_mqttmanager_reload_command()
        return Response(CreatedRoomSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------------------------- labels

EXCLUDE_LABELS_SETTING = "home_assistant_sync_exclude_labels"

# The order of the rows of the candidates table within a room.
_TYPE_ORDER = {"light": 0, "cover": 1, "media_player": 2, "thermostat": 3}


def excluded_label_ids():
    """The label ids in the home_assistant_sync_exclude_labels setting (comma-separated), as a set."""
    value = Settings.objects.filter(name=EXCLUDE_LABELS_SETTING).values_list("value", flat=True).first() or ""
    return {part.strip() for part in value.split(",") if part.strip()}


class HomeAssistantLabelSerializer(serializers.Serializer):
    label_id = serializers.CharField()
    name = serializers.CharField()


class LabelsView(APIView):
    http_method_names = ["get", "head"]

    @extend_schema(responses={200: HomeAssistantLabelSerializer(many=True), 502: HomeAssistantDetailSerializer}, operation_id="list_home_assistant_labels")
    def get(self, request):
        labels = sorted(fetch_registry_or_502()["labels"], key=lambda l: (l["name"].lower(), l["label_id"]))
        return Response(HomeAssistantLabelSerializer(labels, many=True).data)


# ---------------------------------------------------------------------------------------------- entity candidates


def imported_entity_rooms(entity_ids=None):
    """{entity_id: room_id} for every Entity, in any room, whose entity_data.home_assistant_name is an HA entity id."""
    rows = Entity.objects.all()
    if entity_ids is not None:
        rows = rows.filter(entity_data__home_assistant_name__in=list(entity_ids))
    result = {}
    for room_id, data in rows.order_by("id").values_list("room_id", "entity_data"):
        name = (data or {}).get("home_assistant_name")
        if name and name not in result:
            result[name] = room_id
    return result


class EntityCandidateQuerySerializer(serializers.Serializer):
    include_imported = serializers.BooleanField(default=False, help_text="Also list entities already imported into some room (see already_imported_room_id).")
    include_hidden = serializers.BooleanField(default=False, help_text="Also list entities hidden in Home Assistant.")
    include_groups = serializers.BooleanField(default=False, help_text="Also list light groups (lights that have an entity_id attribute).")


class EntityCandidateSerializer(serializers.Serializer):
    entity_id = serializers.CharField()
    ha_name = serializers.CharField(help_text="Home Assistant's friendly name.")
    suggested_name = serializers.CharField(help_text="ha_name without the room or area name in front; what the import should use unless the user edits it.")
    entity_type = serializers.ChoiceField(choices=sorted(_TYPE_ORDER, key=_TYPE_ORDER.get))
    room_id = serializers.IntegerField()
    room_name = serializers.CharField()
    area_id = serializers.CharField()
    hidden = serializers.BooleanField()
    is_group = serializers.BooleanField()
    labels = serializers.ListField(child=serializers.CharField(), help_text="Home Assistant label ids.")
    already_imported_room_id = serializers.IntegerField(allow_null=True, help_text="The room that already holds this entity, if any.")


class EntityCandidatesSerializer(serializers.Serializer):
    candidates = EntityCandidateSerializer(many=True, help_text="Sorted by room order, then type (light, cover, media_player, thermostat), then suggested_name.")
    entities_without_area = serializers.IntegerField(help_text="Supported entities with no area in Home Assistant that would otherwise be listed; they can't be placed in a room.")
    excluded_by_label = serializers.IntegerField(help_text="Entities in linked rooms' areas left out because they carry a label of the home_assistant_sync_exclude_labels setting.")


class EntityCandidatesView(APIView):
    http_method_names = ["get", "head"]

    @extend_schema(
        parameters=[EntityCandidateQuerySerializer],
        responses={200: EntityCandidatesSerializer, 400: ValidationErrorSerializer, 502: HomeAssistantDetailSerializer},
        operation_id="list_home_assistant_entity_candidates",
    )
    def get(self, request):
        query = EntityCandidateQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        include_imported, include_hidden, include_groups = (query.validated_data[k] for k in ("include_imported", "include_hidden", "include_groups"))

        registry = fetch_registry_or_502()
        area_names = {a["area_id"]: a["name"] for a in registry["areas"]}
        rooms = list(Room.objects.filter(home_assistant_link=Room.HomeAssistantLink.LINKED).order_by("displayOrder", "id"))
        room_by_area = {r.home_assistant_area_id: r for r in rooms}
        room_rank = {r.id: index for index, r in enumerate(rooms)}
        excluded = excluded_label_ids()
        imported = imported_entity_rooms()

        def visible(entity, group):
            # The filters that apply to every entity, whether or not it has a room.
            if entity["hidden"] and not include_hidden:
                return False
            if group and not include_groups:
                return False
            return include_imported or entity["entity_id"] not in imported

        rows = []
        without_area = 0
        excluded_by_label = 0
        for entity in registry["entities"]:
            entity_id = entity["entity_id"]
            entity_type = NSPM_TYPE_BY_HA_DOMAIN.get(ha_domain(entity_id))
            if entity_type is None:
                continue
            state = {"entity_id": entity_id, "attributes": entity.get("attributes") or {}}
            group = is_light_group(state)
            room = room_by_area.get(entity["area_id"]) if entity["area_id"] else None
            has_excluded_label = bool(excluded.intersection(entity["labels"]))
            if entity["area_id"] is None:
                if not has_excluded_label and visible(entity, group):
                    without_area += 1
                continue
            if room is None:
                continue
            if has_excluded_label:
                excluded_by_label += 1
                continue
            if not visible(entity, group):
                continue
            ha_name = entity.get("friendly_name") or entity_id
            rows.append(
                {
                    "entity_id": entity_id,
                    "ha_name": ha_name,
                    "suggested_name": suggest_entity_name(ha_name, [room.friendly_name, area_names.get(entity["area_id"], "")], _ENTITY_NAME_MAX) or ha_name[:_ENTITY_NAME_MAX],
                    "entity_type": entity_type,
                    "room_id": room.id,
                    "room_name": room.friendly_name,
                    "area_id": entity["area_id"],
                    "hidden": entity["hidden"],
                    "is_group": group,
                    "labels": entity["labels"],
                    "already_imported_room_id": imported.get(entity_id),
                }
            )
        rows.sort(key=lambda r: (room_rank[r["room_id"]], _TYPE_ORDER[r["entity_type"]], r["suggested_name"].lower(), r["entity_id"]))
        return Response(EntityCandidatesSerializer({"candidates": rows, "entities_without_area": without_area, "excluded_by_label": excluded_by_label}).data)


# ---------------------------------------------------------------------------------------------- import


class ImportItemSerializer(StrictSerializer):
    entity_id = StrictCharField(max_length=_ENTITY_ID_MAX, allow_blank=False)
    room_id = StrictIntegerField()
    entity_type = StrictChoiceField(choices=sorted(_TYPE_ORDER, key=_TYPE_ORDER.get), help_text="Must match the entity's Home Assistant domain: light, cover, media_player or climate (thermostat).")
    friendly_name = TrimmedCharField(allow_blank=False, max_length=_ENTITY_NAME_MAX, help_text="Leading and trailing whitespace is removed.")


class ImportRequestSerializer(StrictSerializer):
    items = ImportItemSerializer(many=True, allow_empty=False, help_text="In the order they should be placed in each room: the order of the candidates table.")


class ImportedEntitySerializer(serializers.Serializer):
    entity_id = serializers.CharField()
    entity_pk = serializers.IntegerField()
    room_id = serializers.IntegerField()
    page_id = serializers.IntegerField()
    position = serializers.IntegerField()


class SkippedEntitySerializer(serializers.Serializer):
    entity_id = serializers.CharField()
    reason = serializers.ChoiceField(choices=["already_imported"])


class ImportResultSerializer(serializers.Serializer):
    created = ImportedEntitySerializer(many=True)
    skipped = SkippedEntitySerializer(many=True, help_text="Entities imported by someone else since the candidates were listed.")
    pages_added = serializers.IntegerField(help_text="Entity pages created because the rooms had too few free slots.")


class ImportView(APIView):
    http_method_names = ["post", "head"]

    @extend_schema(request=ImportRequestSerializer, responses={201: ImportResultSerializer, **_HA_ERRORS}, operation_id="import_home_assistant_entities")
    def post(self, request):
        serializer = ImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["items"]

        entity_ids = [item["entity_id"] for item in items]
        duplicates = sorted({e for e in entity_ids if entity_ids.count(e) > 1})
        if duplicates:
            raise SyncBadRequest(f"Duplicate entity ids in request: {duplicates}")
        for item in items:
            expected = NSPM_TYPE_BY_HA_DOMAIN.get(ha_domain(item["entity_id"]))
            if expected is None:
                raise SyncBadRequest(f'{item["entity_id"]}: Home Assistant domain "{ha_domain(item["entity_id"])}" is not supported.')
            if item["entity_type"] != expected:
                raise SyncBadRequest(f'{item["entity_id"]}: entity_type must be "{expected}", not "{item["entity_type"]}".')

        registry = fetch_registry_or_502()
        ha_entities = {e["entity_id"]: e for e in registry["entities"]}

        created = []
        skipped = []
        pages_added = 0
        with transaction.atomic():
            rooms = {r.id: r for r in Room.objects.select_for_update().filter(id__in={item["room_id"] for item in items})}
            for item in items:
                room = rooms.get(item["room_id"])
                if room is None:
                    raise SyncBadRequest(f'{item["entity_id"]}: unknown room id {item["room_id"]}.')
                if room.home_assistant_link != Room.HomeAssistantLink.LINKED:
                    raise SyncBadRequest(f'{item["entity_id"]}: room "{room.friendly_name}" (id {room.id}) is not linked to a Home Assistant area.')
                entity = ha_entities.get(item["entity_id"])
                if entity is None:
                    raise SyncBadRequest(f'{item["entity_id"]}: not found in Home Assistant.')
                if entity["area_id"] != room.home_assistant_area_id:
                    raise SyncBadRequest(f'{item["entity_id"]}: not in the Home Assistant area of room "{room.friendly_name}" (id {room.id}).')

            # Checked again inside the transaction: another request may have imported some since the list was made.
            already = imported_entity_rooms(entity_ids)
            by_room = {}
            for item in items:
                if item["entity_id"] in already:
                    skipped.append({"entity_id": item["entity_id"], "reason": "already_imported"})
                else:
                    by_room.setdefault(item["room_id"], []).append(item)

            made = {}
            for room_id, room_items in by_room.items():
                placements, new_pages = place_in_room(rooms[room_id], len(room_items))
                pages_added += new_pages
                for item, (page, position) in zip(room_items, placements):
                    state = {"entity_id": item["entity_id"], "attributes": ha_entities[item["entity_id"]].get("attributes") or {}}
                    made[item["entity_id"]] = (
                        Entity.objects.create(
                            room=rooms[room_id],
                            friendly_name=item["friendly_name"],
                            entities_page=page,
                            room_view_position=position,
                            entity_type=item["entity_type"],
                            entity_data=build_entity_data_from_state(item["entity_type"], state),
                        ),
                        page,
                    )
            for item in items:  # Report in request order.
                if item["entity_id"] in made:
                    entity, page = made[item["entity_id"]]
                    created.append({"entity_id": item["entity_id"], "entity_pk": entity.pk, "room_id": entity.room_id, "page_id": page.id, "position": entity.room_view_position})

        logger.info("Imported %d Home Assistant entities (%d skipped, %d pages added)", len(created), len(skipped), pages_added)
        if created:
            send_mqttmanager_reload_command()
        return Response(ImportResultSerializer({"created": created, "skipped": skipped, "pages_added": pages_added}).data, status=status.HTTP_201_CREATED)
