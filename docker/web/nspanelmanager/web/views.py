from django.shortcuts import render, redirect, HttpResponse
from django.core.files.storage import FileSystemStorage
from django.views.decorators.csrf import csrf_exempt

import hashlib

from .models import NSPanel, Room, Light, Settings
from web.settings_helper import get_setting_with_default, set_setting_value


def index(request):
    return render(request, 'index.html', {'nspanels': NSPanel.objects.all()})


def rooms(request):
    return render(request, 'rooms.html', {'rooms': Room.objects.all()})


def rooms_order(request):
    return render(request, 'rooms_order.html', {'rooms': Room.objects.all().order_by('displayOrder')})


def move_room_up(request, room_id: int):
    room = Room.objects.get(id=room_id)
    if room.displayOrder > 1:
        otherRoom = Room.objects.filter(displayOrder=room.displayOrder - 1)
        if otherRoom.count() > 0:
            move_up_room = otherRoom.first()
            move_up_room.displayOrder += 1
            move_up_room.save()

            room.displayOrder -= 1
            room.save()

        # Loop through all rooms and make sure they all follow a pattern
        all_rooms = Room.objects.all().order_by('displayOrder')
        i = 1
        for room in all_rooms:
            room.displayOrder = i
            room.save()
            i += 1

    return redirect('rooms_order')


def move_room_down(request, room_id: int):
    room = Room.objects.get(id=room_id)
    otherRoom = Room.objects.filter(displayOrder=room.displayOrder + 1)
    if otherRoom.count() > 0:
        move_up_room = otherRoom.first()
        move_up_room.displayOrder -= 1
        move_up_room.save()

        room.displayOrder += 1
        room.save()

    # Loop through all rooms and make sure they all follow a pattern
    all_rooms = Room.objects.all().order_by('displayOrder')
    i = 1
    for room in all_rooms:
        room.displayOrder = i
        room.save()
        i += 1

    return redirect('rooms_order')


def edit_room(request, room_id: int):
    return render(request, 'edit_room.html', {'room': Room.objects.filter(id=room_id).first()})


def save_new_room(request):
    new_room = Room()
    new_room.friendly_name = request.POST['friendly_name']
    new_room.save()
    return redirect('rooms')


def update_room_form(request, room_id: int):
    room = Room.objects.filter(id=room_id).first()
    room.friendly_name = request.POST['friendly_name']
    room.save()
    return redirect('edit_room', room_id=room_id)


def remove_light_from_room(request, room_id: int, light_id: int):
    Light.objects.filter(id=light_id).delete()
    return redirect('edit_room', room_id=room_id)


def add_light_to_room(request, room_id: int):
    room = Room.objects.filter(id=room_id).first()
    newLight = Light()
    newLight.room = room
    newLight.friendly_name = request.POST["add_new_light_name"]
    if request.POST["light_type"] == "ceiling":
        newLight.is_ceiling_light = True
    if "dimmable" in request.POST:
        newLight.can_dim = True
    if "color_temperature" in request.POST:
        newLight.can_color_temperature = True
    if "rgb" in request.POST:
        newLight.can_rgb = True
    newLight.save()

    return redirect('edit_room', room_id=room_id)


def settings_page(request):
    data = {}
    data["mqtt_server"] = get_setting_with_default("mqtt_server", "")
    data["mqtt_port"] = get_setting_with_default("mqtt_port", 1883)
    data["mqtt_username"] = get_setting_with_default("mqtt_username", "")
    data["mqtt_password"] = get_setting_with_default("mqtt_password", "")
    data["home_assistant_address"] = get_setting_with_default(
        "home_assistant_address", "")
    data["home_assistant_token"] = get_setting_with_default(
        "home_assistant_token", "")
    data["openhab_address"] = get_setting_with_default(
        "openhab_address", "")
    data["openhab_token"] = get_setting_with_default(
        "openhab_token", "")
    return render(request, 'settings.html', data)


def save_settings(request):
    set_setting_value(name="mqtt_server", value=request.POST["mqtt_server"])
    set_setting_value(name="mqtt_port", value=request.POST["mqtt_port"])
    set_setting_value(name="mqtt_username",
                      value=request.POST["mqtt_username"])
    set_setting_value(name="mqtt_password",
                      value=request.POST["mqtt_password"])
    set_setting_value(name="home_assistant_address",
                      value=request.POST["home_assistant_address"])
    set_setting_value(name="home_assistant_token",
                      value=request.POST["home_assistant_token"])
    set_setting_value(name="openhab_address",
                      value=request.POST["openhab_address"])
    set_setting_value(name="openhab_token",
                      value=request.POST["openhab_token"])

    return redirect('settings')

    # TODO: Make exempt only when Debug = true


@csrf_exempt
def save_new_firmware(request):
    if request.method == 'POST':
        uploaded_file = request.FILES['firmware']
        fs = FileSystemStorage()
        fs.delete("firmware.bin")
        fs.save("firmware.bin", uploaded_file)
    return redirect('/')


# TODO: Make exempt only when Debug = true
@csrf_exempt
def save_new_data_file(request):
    if request.method == 'POST':
        uploaded_file = request.FILES['data_file']
        fs = FileSystemStorage()
        fs.delete("data_file.bin")
        fs.save("data_file.bin", uploaded_file)
    return redirect('/')

# TODO: Make exempt only when Debug = true


@csrf_exempt
def save_new_tft_file(request):
    if request.method == 'POST':
        uploaded_file = request.FILES['tft_file']
        fs = FileSystemStorage()
        fs.delete("gui.tft")
        fs.save("gui.tft", uploaded_file)
        print("Saved new GUI tft file.")
    return redirect('/')


def download_firmware(request):
    fs = FileSystemStorage()
    return HttpResponse(fs.open("firmware.bin").read(), content_type="application/octet-stream")


def download_data_file(request):
    fs = FileSystemStorage()
    return HttpResponse(fs.open("data_file.bin").read(), content_type="application/octet-stream")


def download_tft(request):
    fs = FileSystemStorage()
    return HttpResponse(fs.open("gui.tft").read(), content_type="application/octet-stream")


def checksum_firmware(request):
    fs = FileSystemStorage()
    return HttpResponse(hashlib.md5(fs.open("firmware.bin").read()).hexdigest())


def checksum_data_file(request):
    fs = FileSystemStorage()
    return HttpResponse(hashlib.md5(fs.open("data_file.bin").read()).hexdigest())
