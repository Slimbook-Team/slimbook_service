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

import evdev
import os

BUTTON_SWITCH_USAGE_ID = (iohid.HID_USAGE_PAGE_DIGITIZER << 16) | iohid.HID_USAGE_DIGITIZER_BUTTON_SWITCH
SURFACE_SWITCH_USAGE_ID = (iohid.HID_USAGE_PAGE_DIGITIZER << 16) | iohid.HID_USAGE_DIGITIZER_SURFACE_SWITCH

class Touchpad:
    MODE_UNKNOWN = 0
    MODE_HIDRAW = 1
    MODE_EVDEV = 2
    
    STATE_UNKNOWN = 0
    STATE_LOCKED = 1
    STATE_UNLOCKED = 2
    
    def __init__(self):
        self.mode = Touchpad.MODE_UNKNOWN
        self.report_id = 0
        self.fd = 0
        self.state = Touchpad.STATE_UNKNOWN
        self.device = None
        
        for device in iohid.list_devices():
            fd = os.open(device,os.O_RDWR)
            info = iohid.get_device_info(fd)
            found = False
        
            # ProX/Executive touchpad
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
                            self.report_id = r.id
                            self.fd = fd
                            self.mode = Touchpad.MODE_HIDRAW
                            found = True
                if not found:
                    os.close(fd)
            else:
                os.close(fd)
        
            if found:
                self.get_state()
                return
    
        found = False
        # generic touchpad lookup based on evdev grabing
        for devpath in evdev.list_devices():
            device = evdev.InputDevice(devpath)
    
            for cap in device.capabilities():
                # EV_KEY
                if cap==1:
                    for k in device.capabilities()[cap]:
                        #BTN_TOUCH
                        if k==330:
                            self.device = device
                            self.mode = Touchpad.MODE_EVDEV
                            
                            found = True
                            break
            
            if found:
                self.state = Touchpad.STATE_UNLOCKED
                break
                
    def lock(self):
        if self.mode == Touchpad.MODE_HIDRAW and self.fd>0:
            iohid.set_feature(self.fd,self.report_id,bytes([0x00]))
        
        if self.mode == Touchpad.MODE_EVDEV and self.device:
            self.device.grab()
            self.state = Touchpad.STATE_LOCKED
    
    def unlock(self):
        if self.mode == Touchpad.MODE_HIDRAW and self.fd>0:
            iohid.set_feature(self.fd,self.report_id,bytes([0x03]))
            
        if self.mode == Touchpad.MODE_EVDEV and self.device:
            self.device.ungrab()
            self.state = Touchpad.STATE_UNLOCKED
    
    def toggle(self):
        self.get_state()
    
        if (self.mode == Touchpad.MODE_HIDRAW and self.fd>0) or (self.mode == Touchpad.MODE_EVDEV and self.device):
            if self.state == Touchpad.STATE_LOCKED:
                
                self.unlock()
            elif self.state == Touchpad.STATE_UNLOCKED:
                
                self.lock()
            elif self.state == Touchpad.STATE_UNKNOWN:
                self.unlock()
        
    def get_state(self):
        
        if self.mode == Touchpad.MODE_HIDRAW and self.fd>0:
            self.state = Touchpad.MODE_UNKNOWN
            data = iohid.get_feature(self.fd, self.report_id,1)
            # mask is hardcoded, in the future maybe would be
            # better to obtain it from report descriptor
            data = int(data[0]) & 0x03
            
            if (data == 0):
                self.state = Touchpad.STATE_LOCKED
            else:
                self.state = Touchpad.STATE_UNLOCKED
        
        return self.state
        
    def valid(self):
        return (self.mode != Touchpad.MODE_UNKNOWN)
