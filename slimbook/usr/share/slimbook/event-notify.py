#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Slimbook Service
# Copyright (C) 2022 Slimbook
# In case you modify or redistribute this code you must keep the copyright line above.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from datetime import datetime
from time import sleep
import evdev
import os
import logging
import zmq
import threading

logger = logging.getLogger("main")
logging.basicConfig(format='%(levelname)s-%(message)s')
logger.setLevel(logging.INFO)

PORT = "8999"
context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind(f"tcp://*:{PORT}")

QC71_DIR = '/sys/devices/platform/qc71_laptop'
QC71_mod_loaded = True if os.path.isdir(QC71_DIR) else False


def notify_send(msg):
    dt = datetime.now()
    ts = datetime.timestamp(dt)
    data = {"msg": msg, "timestamp": ts}
    print(data)
    socket.send_json(data)
    #socket.send_string(f"10001 {msg}")


def detect_touchpad():
    touchpad_device = None
    for file in os.listdir('/dev'):
        if file.startswith('hidraw'):
            logger.debug(file)
            data_file = '/sys/class/hidraw/{file}/device/uevent'.format(
                file=file)
            logger.debug(data_file)
            for line in open(data_file).readlines():
                if line.startswith('HID_NAME=') and \
                        line.find('UNIW0001:00 093A:') != -1:
                    try:
                        logger.debug('Found keyboard at: ' +
                                     '/dev/{}'.format(file))
                        touchpad_device = open('/dev/{}'.format(file), 'r')
                    except Exception as e:
                        logger.error(e)
    return touchpad_device


def detect_keyboard():
    keyboard_device_path = None
    for file in os.listdir('/dev/input/by-path'):
        if file.endswith('event-kbd') and file.find('i8042') != -1:
            print(file)
            file_path = os.path.join('/dev/input/by-path', file)
            keyboard_device_path = os.path.realpath(
                os.path.join(file_path, os.readlink(file_path)))
            logger.debug('Found keyboard at: ' + keyboard_device_path)
    return keyboard_device_path


def detect_qc71():
    qc71_device_path = None
    for file in os.listdir('/dev/input/by-path'):
        if file.endswith('qc71_laptop-event'):
            print(file)
            file_path = os.path.join('/dev/input/by-path', file)
            qc71_device_path = os.path.realpath(
                os.path.join(file_path, os.readlink(file_path)))
            logger.debug('Found Qc71 at: ' + qc71_device_path)
    return qc71_device_path


EVENTS = {
    104: {
        "key": "F2",
        "msg": {0: "Super Key Lock disabled",
                1: "Super Key Lock enabled",
                'default': "Super Key Lock state changed"},
        "type": "",
    },
    105: {
        "key": "F5",
        "msg": {0: "Silent Mode disabled",
                1: "Silent Mode enabled",
                'default': "Silent Mode state changed"},
        "type": "",
    },
    118: {
        "key": "Touchpad button",
        "msg": {0: "Touchpad disabled",
                1: "Touchpad enabled",
                'default': "Touchpad state changed"},
        "type": "",
    },
    188: {
        "key": "Performace Button Titan",
        "msg": {0: "Performance Mode changed: Silent",
                1: "Performance Mode changed: Normal",
                2: "Performance Mode changed: Turbo",
                'default': "Performance Mode changed"},
        "type": "",
    },
}


def read_keyboard():
    DEV = detect_touchpad()
    last_event = 0
    send_notification = None
    keyboard_device_path = detect_keyboard()
    device = evdev.InputDevice(keyboard_device_path)
    for event in device.read_loop():
        if event.type == evdev.ecodes.EV_MSC:
            # print(event)
            if event.value != last_event:
                state_int = None
                if event.value == 104:
                    send_notification = True
                    if QC71_mod_loaded:
                        qc71_filename = f"{QC71_DIR}/super_key_lock"
                        file = open(qc71_filename, mode='r')
                        content = file.read()
                        # line = file.readline()
                        file.close()
                        try:
                            state_int = int(content)
                        except:
                            logger.error("Super key lock state read error")
                    else:
                        logger.info('qc71_laptop not loaded')

                elif event.value == 105:
                    send_notification = True

                    if QC71_mod_loaded:
                        qc71_filename = f"{QC71_DIR}/silent_mode"
                        file = open(qc71_filename, mode='r')
                        content = file.read()
                        # line = file.readline()
                        file.close()
                        try:
                            state_int = int(content)
                        except:
                            logger.error("Silent mode state read error")

                    else:
                        logger.info('qc71_laptop not loaded')

                elif event.value == 458811:
                    print("aqui")
                    msg = "En un lugar"
                    notify_send(msg)

                elif event.value == 118:
                    from fcntl import ioctl
                    HIDIOCSFEATURE = 0xC0024806  # 2bytes
                    HIDIOCGFEATURE = 0xC0024807  # 2bytes
                    STATES = {
                        0: {
                            "bytes": bytes([0x07, 0x00]),
                            "action": 1,
                            "msg": "Disabled",
                        },
                        1: {
                            "bytes": bytes([0x07, 0x03]),
                            "action": 0,
                            "msg": "Enabled",
                        },
                    }
                    try:
                        status = ioctl(DEV, HIDIOCGFEATURE, bytes([0x07, 0]))
                        current_status = str(status)
                        # Setting state_int value != NONE we choose the notification according to the device state.
                        state_int = 1 if current_status.find(
                            "x00") != -1 else 0
                        logger.debug(str(state_int) + " " +
                                     str(current_status))
                    except Exception as e:
                        logger.error(e)

                    try:
                        ioctl(DEV, HIDIOCSFEATURE, STATES.get(
                            int(state_int)).get("bytes"))
                    except Exception as e:
                        logger.error(e)

                    send_notification = True

                last_event = event.value
                if EVENTS.get(event.value):
                    msg = (
                        ((EVENTS.get(event.value)).get("msg")).get(state_int)
                        if state_int != None
                        else EVENTS.get(event.value).get("msg").get('default')
                    )
                    if send_notification:
                        logger.info("Should notify " + str(msg))
                        notify_send(msg)
                    else:
                        logger.debug(send_notification)


def read_titan_performance_mode():
    import time
    DNAME = f"{QC71_DIR}"
    FNAME = f"{QC71_DIR}/silent_mode"
    FNAME2 = f"{QC71_DIR}/turbo_mode"

    state_int = None

    def get_content(file_path):
        if os.path.isfile(file_path):
            # open text file in read mode
            text_file = open(file_path, "r")

            # read whole file to a string
            data = text_file.read()

            # close file
            text_file.close()
            return data

    def notify_performance():
        send_notification = True
        if EVENTS.get(188):
            msg = (
                ((EVENTS.get(188)).get("msg")).get(state_int)
                if state_int != None
                else EVENTS.get(188).get("msg").get('default')
            )
            if send_notification:
                logger.info("Should notify " + str(msg))
                notify_send(msg)
            else:
                logger.debug(send_notification)

    MODES = {
        0: 'silent',
        1: 'normal',
        2: 'turbo',
    }

    while True:
        silent = get_content(FNAME)
        turbo = get_content(FNAME2)

        if silent == turbo:
            time.sleep(0.5)
            if silent == turbo:
                mode = 1
        else:
            if int(silent) == 1:
                mode = 0
            else:
                mode = 2

        if not state_int == mode:
            state_int = mode
            # print(MODES.get(state_int))
            notify_performance()
        time.sleep(0.5)


read_kbd_thread = threading.Thread(
    name='my_service', target=read_keyboard)
# read_kbd_thread.daemon = True
read_kbd_thread.start()

if QC71_mod_loaded:
    read_titan_performance_mode_thread = threading.Thread(
        name='my_service', target=read_titan_performance_mode)
    # read_qc71_thread.daemon = True
    read_titan_performance_mode_thread.start()
