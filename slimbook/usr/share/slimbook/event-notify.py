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

import slimbook.info
import slimbook.qc71

import zmq
import evdev

import subprocess
from datetime import datetime
import os
import sys
import logging
import threading
import queue
import time

logger = logging.getLogger("slimbook.service")
logging.basicConfig(format='%(levelname)s-%(message)s')
logger.setLevel(logging.INFO)

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("ipc://{0}".format(common.SLB_IPC_PATH))
os.chmod(common.SLB_IPC_PATH, 0o777)

slb_events = queue.Queue()

BUTTON_SWITCH_USAGE_ID = (iohid.HID_USAGE_PAGE_DIGITIZER << 16) | iohid.HID_USAGE_DIGITIZER_BUTTON_SWITCH
SURFACE_SWITCH_USAGE_ID = (iohid.HID_USAGE_PAGE_DIGITIZER << 16) | iohid.HID_USAGE_DIGITIZER_SURFACE_SWITCH

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

def keyboard_worker():
    
    device_path = "/dev/input/by-path/platform-i8042-serio-0-event-kbd"
    # work around for buggy dmi info
    try:
        devie_path = slimbook.info.keyboard_device()
    except:
        pass
        
    device = evdev.InputDevice(device_path)
    
    state = {}
    
    for event in device.read_loop():
        if (event.type == evdev.ecodes.EV_MSC):
        
            last = state.get(event.value)
            
            if (last == 1):
                state[event.value] = 0
                continue
            else:
                state[event.value] = 1
            
            if (event.value == slimbook.info.SLB_SCAN_QC71_SUPER_LOCK):
                slb_events.put(common.SLB_EVENT_QC71_SUPER_LOCK_CHANGED)
                pass
            
            elif (event.value == slimbook.info.SLB_SCAN_QC71_SILENT_MODE):
                slb_events.put(common.SLB_EVENT_QC71_SILENT_MODE_CHANGED)
            
            elif (event.value == slimbook.info.SLB_SCAN_QC71_TOUCHPAD_SWITCH):
                slb_events.put(common.SLB_EVENT_QC71_TOUCHPAD_CHANGED)
    
            elif (event.value == slimbook.info.SLB_SCAN_Z16_ENERGY_SAVER_MODE):
                slb_events.put(common.SLB_EVENT_Z16_ENERGY_SAVER_MODE)
                
            elif (event.value == slimbook.info.SLB_SCAN_Z16_BALANCED_MODE):
                slb_events.put(common.SLB_EVENT_Z16_BALANCED_MODE)
                
            elif (event.value == slimbook.info.SLB_SCAN_Z16_PERFORMANCE_MODE):
                slb_events.put(common.SLB_EVENT_Z16_PERFORMANCE_MODE)

def qc71_module_worker():
    device = evdev.InputDevice(slimbook.info.module_device())
    
    for event in device.read_loop():
        if (event.type == evdev.ecodes.EV_KEY):
            if (event.value == 1 and event.code == evdev.ecodes.KEY_FN_F2):
                slb_events.put(common.SLB_EVENT_QC71_SUPER_LOCK_CHANGED)
            elif (event.value == 1 and event.code == evdev.ecodes.KEY_FN_F5):
                slb_events.put(common.SLB_EVENT_QC71_SILENT_MODE_CHANGED)
    
def titan_worker():
    silent = slimbook.qc71.silent_mode_get()
    turbo = slimbook.qc71.turbo_mode_get()
    
    current_mode = int(not silent) + int(turbo)
    
    while True:
        silent = slimbook.qc71.silent_mode_get()
        turbo = slimbook.qc71.turbo_mode_get()
        
        mode = int(not silent) + int(turbo)
        
        if (mode != current_mode):
            current_mode = mode
            slb_events.put(common.SLB_EVENT_QC71_SILENT_MODE_CHANGED + mode)
        
        time.sleep(1)
    
def send_notify(code):
    dt = datetime.now()
    ts = datetime.timestamp(dt)
    data = {"code": code, "timestamp": ts}
    socket.send_json(data)
    
def main():

    touchpad_fd = None
    touchpad_report = None

    logger.info("Slimbook service")
    
    model = slimbook.info.get_model()
    platform = slimbook.info.get_platform()
    
    if (model == slimbook.info.SLB_MODEL_UNKNOWN):
        product = slimbook.info.product_name()
        vendor = slimbook.info.board_vendor()
        
        if (vendor.startswith("SLIMBOOK") and product.startswith("EXCALIBUR")):
            # work-around for buggy dmi data
            model = slimbook.info.SLB_MODEL_EXCALIBUR
            platform = slimbook.info.SLB_PLATFORM_Z16
        else:
            logger.error("Unknown model:")
            logger.error("{0}".format(product))
            logger.error("{0}".format(vendor))
            sys.exit(1)
        
    module_loaded = slimbook.info.is_module_loaded()
    
    if (platform == slimbook.info.SLB_PLATFORM_QC71):
        touchpad_fd, touchpad_report = detect_touchpad()
    
        qc71_keyboard_thread = threading.Thread(
            name='slimbook.service.qc71.keyboard', target=keyboard_worker)
        qc71_keyboard_thread.start()
    
        if (module_loaded):
            qc71_module_thread = threading.Thread(
                name='slimbook.service.qc71.module', target=qc71_module_worker)
            qc71_module_thread.start()
        
    
    elif (platform == slimbook.info.SLB_PLATFORM_Z16):
        z16_keyboard_thread = threading.Thread(
            name='slimbook.service.z16.keyboard', target=keyboard_worker)
        z16_keyboard_thread.start()
    
    else:
        logger.info("Unsupported Slimbook model:")
        logger.info("{0}".format(slimbook.info.product_name()))
        logger.info("{0}".format(slimbook.info.board_vendor()))
        sys.exit(0)
        
    while True:
       
        event = slb_events.get()
        
        logger.info("event {0}".format(event))
        
        if (platform == slimbook.info.SLB_PLATFORM_QC71):
            
            if (module_loaded):
                if (event == common.SLB_EVENT_QC71_SUPER_LOCK_CHANGED):
                    value = slimbook.qc71.super_lock_get()
                    if (value == 1):
                        event = common.SLB_EVENT_QC71_SUPER_LOCK_ON
                    else:
                        event = common.SLB_EVENT_QC71_SUPER_LOCK_OFF
                
                elif (event == common.SLB_EVENT_QC71_SILENT_MODE_CHANGED):
                    value = slimbook.qc71.silent_mode_get()
                    
                    if (value == 1):
                        event = common.SLB_EVENT_QC71_SILENT_MODE_ON
                    else:
                        event = common.SLB_EVENT_QC71_SILENT_MODE_OFF
                        
            if (touchpad_fd):
                if (event == common.SLB_EVENT_QC71_TOUCHPAD_CHANGED):
                    status = iohid.get_feature(touchpad_fd, touchpad_report,1)
                    status = int(status[0])
                    
                    
                    if (status == 0):
                        event = common.SLB_EVENT_QC71_TOUCHPAD_ON
                        iohid.set_feature(touchpad_fd,touchpad_report,bytes([0x03]))
                    else:
                        event = common.SLB_EVENT_QC71_TOUCHPAD_OFF
                        iohid.set_feature(touchpad_fd,touchpad_report,bytes([0x00]))
        
        print(event)
        send_notify(event)
        
if __name__=="__main__":
    try:
        main()
    except KeyboardInterrupt as e:
        sys.exit(0)
