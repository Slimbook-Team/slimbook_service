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

import common
import touchpad

import slimbook.info
import slimbook.qc71

from gi.repository import GLib, Gio

import zmq
import evdev
import pyudev

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
logger.setLevel(logging.DEBUG)

context = zmq.Context()
socket_out = context.socket(zmq.PUB)
socket_out.bind("ipc://{0}".format(common.SLB_IPC_PATH))
os.chmod(common.SLB_IPC_PATH, 0o777)

socket_ctl = context.socket(zmq.REP)
#socket_ctl.setsockopt_string(zmq.SUBSCRIBE, "")
#socket_ctl.setsockopt(zmq.SUBSCRIBE, b'')
socket_ctl.bind("ipc://{0}".format(common.SLB_IPC_CTL_PATH))
os.chmod(common.SLB_IPC_CTL_PATH, 0o777)

slb_events = queue.Queue()

settings = {
    common.OPT_TRACKPAD_LOCK: True,
    common.OPT_POWER_PROFILE: True
}

def set_power_profile(profile):
    if (settings[common.OPT_POWER_PROFILE]):
        if (os.path.exists("/usr/bin/powerprofilesctl")):
            subprocess.run(["/usr/bin/powerprofilesctl","set",profile])
        elif (os.path.exists("/usr/bin/tuned-adm")):
            subprocess.run(["/usr/bin/tuned-adm","profile",common.TUNED_PROFILE[profile]])

def get_udev_ac_status(device):
    try:
        ps_type = device.get("POWER_SUPPLY_TYPE")
        ps_online = device.get("POWER_SUPPLY_ONLINE")
        
        if (ps_type and ps_online):
            if (ps_type == "Mains"):
                return int(ps_online)
    except:
        pass
    
    return -1

def upower_hndlr(dbus_proxy, properties_changed, properties_removed):
    props = properties_changed.unpack()
    print(props)
    
def upower_worker():
    upower_proxy = Gio.DBusProxy.new_for_bus_sync(
            bus_type = Gio.BusType.SYSTEM,
            flags = Gio.DBusProxyFlags.NONE,
            info = None,
            name = 'org.freedesktop.UPower.PowerProfiles',
            object_path = '/org/freedesktop/UPower/PowerProfiles',
            interface_name = 'org.freedesktop.UPower.PowerProfiles',
            cancellable = None)

    upower_proxy.connect('g-properties-changed', upower_hndlr)
    print(upower_proxy.get_cached_property("ActiveProfile"))

    ctx = GLib.MainContext.default()
    
    while (ctx.iteration(True)):
        pass

def udev_worker():
    context = pyudev.Context()
    
    for device in context.list_devices(subsystem="power_supply"):
        status = get_udev_ac_status(device)
        if (status >=0):
            logger.info("AC status:{0}".format(status))
            slb_events.put(common.SLB_EVENT_AC_OFFLINE + status)
    
    for device in context.list_devices(subsystem="input"):
        if device.get("ID_PATH") == "platform-qc71_laptop":
            if (device.get("DEVNAME")):
                slb_events.put(common.SLB_EVENT_QC71_INPUT_LOADED)
            
    monitor = pyudev.Monitor.from_netlink(context)
    #monitor.filter_by('power_supply')
    for device in iter(monitor.poll, None):
        if device.subsystem == "power_supply":
            status = get_udev_ac_status(device)
            if (status >=0):
                logger.info("AC status:{0}".format(status))
                slb_events.put(common.SLB_EVENT_AC_OFFLINE + status)
        elif device.subsystem == "input":
            if (device.get("ID_PATH") == "platform-qc71_laptop" and device.get("DEVNAME")):
                if (device.action == "add"):
                    slb_events.put(common.SLB_EVENT_QC71_INPUT_LOADED)
                else:
                    slb_events.put(common.SLB_EVENT_QC71_INPUT_UNLOADED)
                
def zmq_worker():
    
    while True: 
        if (socket_ctl.poll(timeout = 100) == 0):
            continue
        data = socket_ctl.recv_json()
        
        cmd = data.get("cmd")
        
        if (cmd and cmd == common.CMD_LOAD_SETTINGS):
            
            keys = data.get("settings")
            if (keys):
                logger.info("Updating settings...")
                for k in keys:
                    logger.info("{0}={1}".format(k,keys[k]))
                    settings[k] = keys[k]
                
        
        socket_ctl.send_json({})
    
def keyboard_worker():
    
    device_path = "/dev/input/by-path/platform-i8042-serio-0-event-kbd"
    # work around for buggy dmi info
    try:
        device_path = slimbook.info.keyboard_device()
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
            
            elif (event.value == slimbook.info.SLB_SCAN_QC71_SILENT_MODE):
                logger.debug("qc71 performance change requested (i8042)")
                slb_events.put(common.SLB_EVENT_QC71_SILENT_MODE_CHANGED)
            
            elif (event.value == slimbook.info.SLB_SCAN_TOUCHPAD_SWITCH):
                slb_events.put(common.SLB_EVENT_TOUCHPAD_CHANGED)
    
            elif (event.value == slimbook.info.SLB_SCAN_ENERGY_SAVER_MODE):
                slb_events.put(common.SLB_EVENT_ENERGY_SAVER_MODE)
                
            elif (event.value == slimbook.info.SLB_SCAN_BALANCED_MODE):
                slb_events.put(common.SLB_EVENT_BALANCED_MODE)
                
            elif (event.value == slimbook.info.SLB_SCAN_PERFORMANCE_MODE):
                slb_events.put(common.SLB_EVENT_PERFORMANCE_MODE)

def qc71_module_worker():
    logger.debug("qc71 keyboard worker start")
    device = evdev.InputDevice(slimbook.info.module_device())
    try:
        for event in device.read_loop():
            if (event.type == evdev.ecodes.EV_KEY):
                if (event.value == 1 and event.code == evdev.ecodes.KEY_FN_F2):
                    slb_events.put(common.SLB_EVENT_QC71_SUPER_LOCK_CHANGED)
                elif (event.value == 1 and event.code == evdev.ecodes.KEY_FN_F5):
                    logger.debug("qc71 performance change requested")
                    slb_events.put(common.SLB_EVENT_QC71_SILENT_MODE_CHANGED)
                elif (event.value == 1 and event.code == evdev.ecodes.KEY_FN_F12):
                    slb_events.put(common.SLB_EVENT_WEBCAM_CHANGED)
    except:
        pass
    logger.info("qc71 keyboard thread end")
    
def send_notify(code):
    dt = datetime.now()
    ts = datetime.timestamp(dt)
    data = {"code": code, "timestamp": ts}
    socket_out.send_json(data)
    
def main():
    logger.info("Slimbook service")

    zmq_thread = threading.Thread(
            name='slimbook.service.zmq', target=zmq_worker)
    zmq_thread.start()
    
    udev_thread = threading.Thread(
            name='slimbook.service.udev', target=udev_worker)
    udev_thread.start()
    
    upower_thread = threading.Thread(
            name='slimbook.service.upower', target=upower_worker)
    upower_thread.start()
    
        
    tpad = touchpad.Touchpad()
    if (tpad.valid()):
        tpad_mode_name = {touchpad.Touchpad.MODE_HIDRAW:"hidraw",touchpad.Touchpad.MODE_EVDEV:"evdev"}
        logger.info("Found a touchpad device of type {0}".format(tpad_mode_name[tpad.mode]))
    
    keyboard_platforms = [slimbook.info.SLB_PLATFORM_Z16,slimbook.info.SLB_PLATFORM_HMT16]
    
    model = slimbook.info.get_model()
    platform = slimbook.info.get_platform()
    family = slimbook.info.get_family()

    logger.info("platform:{0:04x}".format(platform))
    logger.info("model:{0:04x}".format(model))
    
    if (model == slimbook.info.SLB_MODEL_UNKNOWN):
        product = slimbook.info.product_name().lower()
        vendor = slimbook.info.board_vendor().lower()
        
        if (product.startswith("excalibur")):
            # work-around for buggy dmi data
            model = slimbook.info.SLB_MODEL_EXCALIBUR
            platform = slimbook.info.SLB_PLATFORM_Z16
        else:
            logger.warning("Unknown model:")
            logger.warning("Product:[{0}]".format(slimbook.info.product_name()))
            logger.warning("Vendor:[{0}]".format(slimbook.info.board_vendor()))
    
    module_loaded = slimbook.info.is_module_loaded()
    
    if (platform == slimbook.info.SLB_PLATFORM_QC71):
        qc71_keyboard_thread = threading.Thread(
            name='slimbook.service.qc71.keyboard', target=keyboard_worker)
        qc71_keyboard_thread.start()
            
        if (module_loaded):
            logger.info("Setting qc71 manual mode")
            slimbook.qc71.manual_control_set(True)
            
            #qc71_module_thread = threading.Thread(
                #name='slimbook.service.qc71.module', target=qc71_module_worker)
            #qc71_module_thread.start()
        
        else:
            logger.warning("QC71 kernel module is not available!")
            
    elif (platform in keyboard_platforms):
        keyboard_thread = threading.Thread(
            name='slimbook.service.generic.keyboard', target=keyboard_worker)
        keyboard_thread.start()
    
    else:
        logger.warning("No event handler for this model!")
        
    cached_events = {}
    
    while True:
       
        event = slb_events.get()
        now = time.time()
        
        logger.debug("event {0}".format(event))
        
        cached = cached_events.get(event)
        
        if cached:
            delta =  now - cached
            if delta > 0.750:
                cached_events[event] = now
            else:
                logger.debug("ignored duplicated event {0} ({1})".format(event,delta))
                continue
        else:
            cached_events[event] = now
        
        # no need to bother user with this event as it is already notified elsewhere
        if (event == common.SLB_EVENT_AC_OFFLINE or event == common.SLB_EVENT_AC_ONLINE):
            continue
        
        if (family == slimbook.info.SLB_MODEL_EXCALIBUR):
            if (event == common.SLB_EVENT_ENERGY_SAVER_MODE):
                set_power_profile(common.POWER_PROFILE_POWER_SAVER)
            elif (event == common.SLB_EVENT_BALANCED_MODE):
                set_power_profile(common.POWER_PROFILE_BALANCED)
            elif (event == common.SLB_EVENT_PERFORMANCE_MODE):
                set_power_profile(common.POWER_PROFILE_PERFORMANCE)

        if (platform == slimbook.info.SLB_PLATFORM_QC71):
            if (event == common.SLB_EVENT_QC71_INPUT_LOADED):
                qc71_module_thread = threading.Thread(
                    name='slimbook.service.qc71.module', target=qc71_module_worker)
                qc71_module_thread.start()
                
                module_loaded = True
                continue
                
            if (event == common.SLB_EVENT_QC71_INPUT_UNLOADED):
                module_loaded = False
                continue
                
            if (module_loaded):
                if (event == common.SLB_EVENT_QC71_SUPER_LOCK_CHANGED):
                    value = slimbook.qc71.super_lock_get()
                    if (value == 1):
                        event = common.SLB_EVENT_QC71_SUPER_LOCK_ON
                    else:
                        event = common.SLB_EVENT_QC71_SUPER_LOCK_OFF
                
                # General Performance event on QC71
                elif (event == common.SLB_EVENT_QC71_SILENT_MODE_CHANGED):
                    value = slimbook.qc71.profile_get()
                    logger.debug("current performance:{0}".format(common.POWER_PROFILE_NAME[value]))
                    
                    if (family in common.QC71_DOUBLE_PROFILE):
                        if (value == slimbook.info.SLB_QC71_PROFILE_SILENT):
                            slimbook.qc71.profile_set(slimbook.info.SLB_QC71_PROFILE_NORMAL)
                            logger.debug("switching to {0}".format(common.POWER_PROFILE_NAME[slimbook.info.SLB_QC71_PROFILE_NORMAL]))
                            event = common.SLB_EVENT_QC71_SILENT_MODE_OFF
                            set_power_profile(common.POWER_PROFILE_BALANCED)
                            
                        elif (value == slimbook.info.SLB_QC71_PROFILE_NORMAL):
                            slimbook.qc71.profile_set(slimbook.info.SLB_QC71_PROFILE_SILENT)
                            logger.debug("switching to {0}".format(common.POWER_PROFILE_NAME[slimbook.info.SLB_QC71_PROFILE_SILENT]))
                            event = common.SLB_EVENT_QC71_SILENT_MODE_ON
                            set_power_profile(common.POWER_PROFILE_POWER_SAVER)
                        
                    if (family in common.QC71_TRIPLE_PROFILE):
                        if (value == slimbook.info.SLB_QC71_PROFILE_PERFORMANCE):
                            slimbook.qc71.profile_set(slimbook.info.SLB_QC71_PROFILE_ENERGY_SAVER)
                            logger.debug("switching to {0}".format(common.POWER_PROFILE_NAME[slimbook.info.SLB_QC71_PROFILE_ENERGY_SAVER]))
                            event = common.SLB_EVENT_ENERGY_SAVER_MODE
                            set_power_profile(common.POWER_PROFILE_POWER_SAVER)
                            
                        elif (value == slimbook.info.SLB_QC71_PROFILE_ENERGY_SAVER):
                            slimbook.qc71.profile_set(slimbook.info.SLB_QC71_PROFILE_BALANCED)
                            logger.debug("switching to {0}".format(common.POWER_PROFILE_NAME[slimbook.info.SLB_QC71_PROFILE_BALANCED]))
                            event = common.SLB_EVENT_BALANCED_MODE
                            set_power_profile(common.POWER_PROFILE_BALANCED)
                            
                        elif (value == slimbook.info.SLB_QC71_PROFILE_BALANCED):
                            slimbook.qc71.profile_set(slimbook.info.SLB_QC71_PROFILE_PERFORMANCE)
                            logger.debug("switching to {0}".format(common.POWER_PROFILE_NAME[slimbook.info.SLB_QC71_PROFILE_PERFORMANCE]))
                            event = common.SLB_EVENT_PERFORMANCE_MODE
                            set_power_profile(common.POWER_PROFILE_PERFORMANCE)

                elif (event == common.SLB_EVENT_AC_OFFLINE):
                
                    if (family == slimbook.info.SLB_MODEL_CREATIVE):
                        slimbook.qc71.profile_set(slimbook.info.SLB_QC71_PROFILE_ENERGY_SAVER)
                        event = common.SLB_EVENT_QC71_DYNAMIC_MODE

        if (event == common.SLB_EVENT_TOUCHPAD_CHANGED):
            if (not settings[common.OPT_TRACKPAD_LOCK]):
                continue
            
            if (tpad.valid()):
                tpad.toggle()
                state = tpad.get_state()
                
                if (state == touchpad.Touchpad.STATE_LOCKED):
                    event = common.SLB_EVENT_TOUCHPAD_OFF
                elif (state == touchpad.Touchpad.STATE_UNLOCKED):
                    event = common.SLB_EVENT_TOUCHPAD_ON
                else:
                    continue
                
            else:
                #discard event
                continue
                    
        logger.debug("out event {0}".format(event))
        send_notify(event)
        
if __name__=="__main__":
    try:
        main()
    except KeyboardInterrupt as e:
        sys.exit(0)
