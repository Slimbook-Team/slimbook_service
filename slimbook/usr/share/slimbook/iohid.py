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

import os
import glob
import struct
from fcntl import ioctl

HID_MAX_DESCRIPTOR_SIZE = 4096

HIDIOCSFEATURE = 0xC0004806
HIDIOCGFEATURE = 0xC0004807
HIDIOCGRDESCSIZE = 0x80044801
HIDIOCGRDESC = 0x90044802
HIDIOCGRAWINFO = 0x80084803

HID_BUS_USB = 0x03
HID_BUS_HIL = 0x04
HID_BUS_BLUETOOTH = 0x05
HID_BUS_VIRTUAL = 0x06
HID_BUS_I2C = 0x18

HID_BUS = {
    HID_BUS_USB : "usb",
    HID_BUS_HIL : "hil",
    HID_BUS_BLUETOOTH : "bluetooth",
    HID_BUS_VIRTUAL : "virtual",
    HID_BUS_I2C : "i2c"
}

HID_SIZE = {
    0:0,
    1:1,
    2:2,
    3:4
    }

HID_TYPE_MAIN = 0
HID_TYPE_GLOBAL = 1
HID_TYPE_LOCAL = 2

HID_MAIN_INPUT = 0x80
HID_MAIN_OUTPUT = 0x90
HID_MAIN_FEATURE = 0xB0 
HID_MAIN_COLLECTION = 0xA0
HID_MAIN_END_COLLECTION = 0xC0

HID_LOCAL_USAGE = 0x08

HID_GLOBAL_USAGE_PAGE = 0x04
HID_GLOBAL_REPORT_ID = 0x84

HID_COLLECTION_PHYSICAL = 0x00
HID_COLLECTION_APPLICATION = 0x01
HID_COLLECTION_LOGICAL = 0x02

HID_USAGE_PAGE_DIGITIZER = 0x0D

HID_USAGE_DIGITIZER_DIGITIZER = 0x01
HID_USAGE_DIGITIZER_PEN = 0x02
HID_USAGE_DIGITIZER_DEVICE_CONFIGURATION = 0x0E
HID_USAGE_DIGITIZER_PEN = 0x22
HID_USAGE_DIGITIZER_DEVICE_MODE = 0x52
HID_USAGE_DIGITIZER_SURFACE_SWITCH = 0x57
HID_USAGE_DIGITIZER_BUTTON_SWITCH = 0x58

HID_COLLECTION = {
    0x00:"Physical",
    0x01:"Application",
    0x02:"Logical",
    0x03:"Report",
    0x04:"Named array",
    0x05:"Usage Switch",
    0x06:"Usage Mod"
    }
    
HID_MAIN = {
    0x80:"Input",
    0x90:"Output",
    0xB0:"Feature",
    0xA0:"Collection",
    0xC0:"End Collection"
    }

class DeviceInfo:
    def __init__(self,bus,vendor,product):
        self.bus = bus
        self.vendor = vendor
        self.product = product
        
    def __str__(self):
        return "{0} {1:04x} {2:04x}".format(HID_BUS[self.bus],self.vendor,self.product)

class Collection:
    def __init__(self,collection_type, usage_page, usage):
        self.collection_type = collection_type
        self.usage_page = usage_page
        self.usage = usage
        self.children = []
        
    def __str__(self):
        text = "Collection {0}, Usage Page {1:02x}, Usage {2:02x}\n".format(HID_COLLECTION[self.collection_type],self.usage_page,self.usage)
        for c in self.children:
            text = text + "...."+ str(c)
        
        return text
        
class Report:
    def __init__(self,id,report_type,usages):
        self.id = id
        self.report_type = report_type
        self.usages = usages
        
    def __str__(self):
        text = "{0} {1}\n".format(self.id,HID_MAIN[self.report_type])
        
        for u in self.usages:
            text = text + "...." + "{0:04x}\n".format(u)
        
        return text

def list_devices():
    return glob.glob("/dev/hidraw*")

def get_device_info(fd):
    info = struct.pack("Ihh",0,0,0)
    status = ioctl(fd,HIDIOCGRAWINFO,info)
    data = struct.unpack("Ihh",status)
    
    return DeviceInfo(data[0], data[1], data[2])

def set_feature(fd,id,data):
    cmd = HIDIOCSFEATURE | ((1 + len(data))<<16)
    data = bytes([id]) + data
    return ioctl(fd,cmd,data)

def get_feature(fd,id,size):
    cmd = HIDIOCGFEATURE | ((1 + size)<<16)
    data = bytes([id]) + bytes([0]*size)
    return ioctl(fd,cmd,data)[1:]

def get_report_descriptor(fd):
    data = struct.pack("I",0)
    status = ioctl(fd, HIDIOCGRDESCSIZE, data)
    report_size = struct.unpack("I",status)[0]
    
    report = struct.pack("I{0}s".format(report_size),report_size,bytes([0]*report_size))
    status = ioctl(fd, HIDIOCGRDESC, report)
    
    return struct.unpack("I{0}s".format(report_size),status)[1]

def parse_report_descriptor(data):
    n = 0
    report_size = len(data)
    usage_page = 0
    usage = 0
    report_id = 0
    reports = []
    usages = []
    
    while (n<report_size):
        byte = data[n]
        bSize = HID_SIZE[byte & 0x03]
        bType = (byte & 0x0C) >> 2
        bTag = (byte & 0xF0)
        
        if (bType == HID_TYPE_MAIN):
            main_type = byte & 0xFC
            
            if (main_type == HID_MAIN_COLLECTION):
                collection_type = data[n+1]

            if (main_type == HID_MAIN_END_COLLECTION):
                pass
                
            if (main_type == HID_MAIN_INPUT or main_type == HID_MAIN_OUTPUT or main_type == HID_MAIN_FEATURE):
                
                reports.append(Report(report_id,main_type,usages))
                usages = []
        
        if (bType == HID_TYPE_GLOBAL):
            global_type = byte & 0xFC

            if (global_type == HID_GLOBAL_USAGE_PAGE):
                usage_page = data[n+1]

            if (global_type == HID_GLOBAL_REPORT_ID):
                report_id = data[n+1]
        
        if (bType == HID_TYPE_LOCAL):
            local_type = byte & 0xFC

            if (local_type == HID_LOCAL_USAGE):
                usage = data[n+1]
                
                usages.append((usage_page<<16) | usage)
        
        n = n + bSize
        n = n + 1
    
    return reports

