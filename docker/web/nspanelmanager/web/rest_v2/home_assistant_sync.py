"""Linking NSPM rooms to Home Assistant areas, and making rooms from areas (/rest/v2/home_assistant/...)."""

import logging

from django.db import transaction
from django.db.models import Max
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from web.apps import send_mqttmanager_reload_command
from web.ha_area_matching import suggest_area
from web.home_assistant_api import HomeAssistantError, fetch_home_assistant_registry
from web.models import IgnoredHomeAssistantArea, Room

from .rooms import StrictCharField, StrictChoiceField, StrictIntegerField, TrimmedCharField, create_entity_pages_for_room
from .schema import extend_schema

logger = logging.getLogger(__name__)

_FRIENDLY_NAME_MAX = Room._meta.get_field("friendly_name").max_length
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
