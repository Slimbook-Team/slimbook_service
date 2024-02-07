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

import iohid
import common

import subprocess
from datetime import datetime
import evdev
import os
import logging
import zmq
import threading
import time

logger = logging.getLogger("main")
logging.basicConfig(format='%(levelname)s-%(message)s')
logger.setLevel(logging.INFO)

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("ipc://{0}".format(common.SLB_IPC_PATH))
os.chmod(common.SLB_IPC_PATH, 0o777)

QC71_DIR = '/sys/devices/platform/qc71_laptop'
QC71_mod_loaded = True if os.path.isdir(QC71_DIR) else False

QC71_MOD_DIR = f"{QC71_DIR}"
SILENT_FILE = f"{QC71_DIR}/silent_mode"
TURBO_FILE = f"{QC71_DIR}/turbo_mode"

BUTTON_SWITCH_USAGE_ID = (iohid.HID_USAGE_PAGE_DIGITIZER << 16) | iohid.HID_USAGE_DIGITIZER_BUTTON_SWITCH
SURFACE_SWITCH_USAGE_ID = (iohid.HID_USAGE_PAGE_DIGITIZER << 16) | iohid.HID_USAGE_DIGITIZER_SURFACE_SWITCH


#is_titan = True if "TITAN" in subprocess.getstatusoutput("sudo dmidecode --string baseboard-product-name")[1] else False
is_titan = False
slimbook_model = None

def notify_send(msg):
    dt = datetime.now()
    ts = datetime.timestamp(dt)
    data = {"msg": msg, "timestamp": ts}
    logger.debug("notify:"+str(data))
    socket.send_json(data)


def detect_touchpad():
    touchpad_fd = None
    touchpad_report = -1
    
    for device in iohid.list_devices():
        fd = open(device,"rb")
        info = iohid.get_device_info(fd)
        found = False
        
        if (info.bus == iohid.HID_BUS_I2C and info.vendor == 0x93A):
            report = iohid.get_report_descriptor(fd)
            reports = iohid.parse_report_descriptor(report)
            
            for r in reports:
                if r.report_type == iohid.HID_MAIN_FEATURE:
                    button_switch = False
                    surface_switch = False
                    
                    for usage in r.usages:
                        
                        if usage == BUTTON_SWITCH_USAGE_ID:
                            button_switch = True
                        if usage == SURFACE_SWITCH_USAGE_ID:
                            surface_switch = True
                    
                    if button_switch and surface_switch:
                        touchpad_report = r.id
                        touchpad_fd = fd
                        found = True
                        logger.info("Found touchpad: {0} report ID {1}".format(device,r.id))
            if not found:
                fd.close()
        else:
            fd.close()
        
        if found:
            break
    
    return (touchpad_fd,touchpad_report)


def detect_keyboard():
    keyboard_device_path = None
    for file in os.listdir('/dev/input/by-path'):
        if file.endswith('event-kbd') and file.find('i8042') != -1:
            file_path = os.path.join('/dev/input/by-path', file)
            keyboard_device_path = os.path.realpath(
                os.path.join(file_path, os.readlink(file_path)))
            logger.info('Found keyboard: ' + keyboard_device_path)
    return keyboard_device_path


def detect_qc71():
    qc71_device_path = None
    for file in os.listdir('/dev/input/by-path'):
        if file.endswith('qc71_laptop-event'):
            file_path = os.path.join('/dev/input/by-path', file)
            qc71_device_path = os.path.realpath(
                os.path.join(file_path, os.readlink(file_path)))
            logger.info('Found qc71 input: ' + qc71_device_path)
    return qc71_device_path


def get_content(file_path):
    if os.path.isfile(file_path):
        # open text file in read mode
        text_file = open(file_path, "r")

        # read whole file to a string
        data = text_file.read()

        # close file
        text_file.close()
        return data

EVENTS = {
    104: {
        "key": "F2",
        "msg": {0: "Super Key Lock disabled",
                1: "Super Key Lock enabled",
                'default': "Super Key Lock state changed"},
        "type": "",
    },
    165: {  # f2 ON QC71 module
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

MODES = {
        0: 'silent',
        1: 'normal',
        2: 'turbo',
    }


def read_keyboard():
    touchpad_fd, touchpad_report = detect_touchpad()
    last_event = 0
    send_notification = None
    keyboard_device_path = detect_keyboard()
    device = evdev.InputDevice(keyboard_device_path)
    last_event = None
    
    for event in device.read_loop():
        if event.type == evdev.ecodes.EV_MSC:
            
            # event filter, it has some room for improvement but it works good enought
            if (last_event and event.value == last_event.value):
                delta = event.timestamp() - last_event.timestamp()
                
                if (delta < 0.5):
                    logger.debug("Event filtered (<0.5s)")
                    continue
                    
            state_int = None
            
            # super key lock
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
                        last_event = event
                    except:
                        logger.error("Super key lock state read error")
                else:
                    logger.info('qc71_laptop not loaded')

            # silent mode/performance
            elif event.value == 105:
                send_notification = True

                if QC71_mod_loaded:
                    qc71_filename = f"{QC71_DIR}/silent_mode"
                    file = open(qc71_filename, mode='r')
                    content = file.read()
                    # line = file.readline()
                    file.close()
                    try:
                        logger.debug("perfomance changed:"+str(content))
                        state_int = int(content)
                        last_event = event
                    except:
                        logger.error("Silent mode state read error")

                else:
                    logger.info('qc71_laptop not loaded')

            # what is this?
            elif event.value == 458811:
                pass

            # touchpad switch
            elif event.value == 118:
                STATES = {
                    0: {
                        "bytes": bytes([0x00]),
                        "action": 1,
                        "msg": "Disabled",
                    },
                    1: {
                        "bytes": bytes([0x03]),
                        "action": 0,
                        "msg": "Enabled",
                    },
                }
                try:
                    # expecting a 1 byte size response
                    status = iohid.get_feature(touchpad_fd, touchpad_report,1)
                    current_status = int(status[0])
                    state_int = 1 if current_status == 0 else 0
                    logger.debug("touchpad status changed:{0}".format(current_status))
                    iohid.set_feature(touchpad_fd,touchpad_report,STATES.get(int(state_int)).get("bytes"))
                    last_event = event
                except Exception as e:
                    logger.error(e)

                send_notification = True

            if EVENTS.get(event.value):
                msg = (
                    ((EVENTS.get(event.value)).get("msg")).get(state_int)
                    if state_int != None
                    else EVENTS.get(event.value).get("msg").get('default')
                )
                if send_notification:
                    logger.debug("Should notify " + str(msg))
                    notify_send(msg)
                else:
                    logger.debug(send_notification)



def read_qc71():
    last_event = 0
    send_notification = None
    keyboard_device_path = detect_qc71()
    device = evdev.InputDevice(keyboard_device_path)
    for event in device.read_loop():
        if event.type == evdev.ecodes.EV_MSC:
            # print(event)
            # if event.value != last_event:
            state_int = None
            if event.value == 165:
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

            elif event.value == 188:
                if QC71_mod_loaded and not is_titan:
                    send_notification = True
                    silent = get_content(SILENT_FILE)
                    try:
                        state_int = int(silent)
                    except:
                        logger.error("Silent mode state read error")

                else:
                    send_notification = False

            last_event = event.value
            if EVENTS.get(event.value):
                msg = (
                    ((EVENTS.get(event.value)).get("msg")).get(state_int)
                    if state_int != None
                    else EVENTS.get(event.value).get("msg").get('default')
                )
                if send_notification:
                    logger.debug("Should notify " + str(msg))
                    notify_send(msg)
                else:
                    logger.debug(send_notification)

def read_titan_performance_mode():
    state_int = None
    send_notification = False
    
    def notify_performance():
        event_value = 188
        if EVENTS.get(event_value) and send_notification:
            msg = (
                ((EVENTS.get(event_value)).get("msg")).get(state_int)
                if state_int != None
                else EVENTS.get(event_value).get("msg").get('default')
            )
            logger.info("TITAN - Should notify " + str(msg))
            notify_send(msg)
        else:
            logger.debug(send_notification)

    while True:
        silent = get_content(SILENT_FILE)
        turbo = get_content(TURBO_FILE)

        if int(silent) == 1:
            mode = 0
        elif int(turbo) == 1:
            mode = 2
        elif silent == turbo:
            time.sleep(0.5)
            if silent == turbo: # NORMAL
                mode = 1
        
        #logger.info(str(mode)+"   " +str(state_int))
            
        if not state_int == mode: # MODE CHANGED
            send_notification = True if state_int != None else False
            state_int = mode 
            notify_performance()
            
        time.sleep(0.5)


def main():

    logger.info("Slimbook service")
    
    slimbook_model = get_content("/sys/class/dmi/id/product_name").strip()
    logger.info("Model: {0}".format(slimbook_model))
    
    is_titan = (slimbook_model == "TITAN") or (slimbook_model == "HERO-RPL-RTX")

    read_kbd_thread = threading.Thread(
        name='my_service', target=read_keyboard)
    read_kbd_thread.start()

    if QC71_mod_loaded:
        if is_titan:
            read_titan_performance_mode_thread = threading.Thread(
                name='my_service', target=read_titan_performance_mode
            )
            read_titan_performance_mode_thread.start()

        
        read_qc71_thread = threading.Thread(
            name='my_service', target=read_qc71
        )
        read_qc71_thread.start()
    else:
        logger.warning("qc71_laptop kernel module is not loaded")
        
if __name__=="__main__":
    main()
