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

import slimbook.info
import slimbook.smbios

import os, codecs, json
import subprocess
import locale
import gettext
import requests
import re

try:
    current_locale, encoding = locale.getdefaultlocale()
    language = gettext.translation(APP, LANGDIR, [current_locale])
    language.install()
    _ = language.gettext
except Exception as e:
    _ = str

SLB_EVENT_QC71_SILENT_MODE_CHANGED = 0x00
SLB_EVENT_QC71_SILENT_MODE_ON = 0x01
SLB_EVENT_QC71_SILENT_MODE_OFF = 0x02

SLB_EVENT_QC71_SUPER_LOCK_CHANGED = 0x03
SLB_EVENT_QC71_SUPER_LOCK_ON = 0x04
SLB_EVENT_QC71_SUPER_LOCK_OFF = 0x05

SLB_EVENT_QC71_SILENT_MODE = 0x06
SLB_EVENT_QC71_NORMAL_MODE = 0x07
SLB_EVENT_QC71_PERFORMANCE_MODE = 0x08

#this events are shared on several platforms and no longer are qc71 exclusive
SLB_EVENT_TOUCHPAD_CHANGED = 0x0100
SLB_EVENT_TOUCHPAD_ON = 0x0200
SLB_EVENT_TOUCHPAD_OFF = 0x0300
SLB_EVENT_WEBCAM_CHANGED = 0x0400
SLB_EVENT_WEBCAM_ON = 0x0500
SLB_EVENT_WEBCAM_OFF = 0x0600

SLB_EVENT_ENERGY_SAVER_MODE = 0x0700
SLB_EVENT_BALANCED_MODE = 0x0800
SLB_EVENT_PERFORMANCE_MODE = 0x0900

SLB_EVENT_DATA = {
    SLB_EVENT_QC71_SILENT_MODE_ON : [_("Silent Mode enabled"),"power-profile-power-saver-symbolic"],
    SLB_EVENT_QC71_SILENT_MODE_OFF : [_("Silent Mode disabled"),"power-profile-balanced-symbolic"],
    SLB_EVENT_QC71_SILENT_MODE_CHANGED : [_("Silent Mode changed"),"power-profile-balanced-symbolic"],
    
    SLB_EVENT_QC71_SUPER_LOCK_ON : [_("Super Key Lock enabled"),"preferences-system-privacy-symbolic"],
    SLB_EVENT_QC71_SUPER_LOCK_OFF : [_("Super Key Lock disabled"),"preferences-system-privacy-symbolic"],
    SLB_EVENT_QC71_SUPER_LOCK_CHANGED : [_("Super Key Lock changed"),"preferences-system-privacy-symbolic"],
    
    SLB_EVENT_QC71_SILENT_MODE : [_("Silent Mode"),"power-profile-power-saver-symbolic"],
    SLB_EVENT_QC71_NORMAL_MODE : [_("Normal Mode"),"power-profile-balanced-symbolic"],
    SLB_EVENT_QC71_PERFORMANCE_MODE : [_("Performance Mode"),"power-profile-performance-symbolic"],
    
    SLB_EVENT_TOUCHPAD_ON : [_("Touchpad enabled"),"input-touchpad-symbolic"],
    SLB_EVENT_TOUCHPAD_OFF : [_("Touchpad disabled"),"input-touchpad-symbolic"],
    SLB_EVENT_TOUCHPAD_CHANGED : [_("Touchpad changed"),"input-touchpad-symbolic"],
    SLB_EVENT_WEBCAM_CHANGED : [_("Webcam changed"),"preferences-system-privacy-symbolic"],
    SLB_EVENT_WEBCAM_ON : [_("Webcam enabled"),"preferences-system-privacy-symbolic"],
    SLB_EVENT_WEBCAM_OFF : [_("Webcam disabled"),"preferences-system-privacy-symbolic"],

    SLB_EVENT_ENERGY_SAVER_MODE : [_("Energy Saver"),"power-profile-power-saver-symbolic"],
    SLB_EVENT_BALANCED_MODE : [_("Balanced"),"power-profile-balanced-symbolic"],
    SLB_EVENT_PERFORMANCE_MODE : [_("Performance"),"power-profile-performance-symbolic"]
}

PARAMS = {
            'first-time': True,
            'version': '',
            'autostart': True,
            'theme': 'light',
            'show': True,
            'notifications' : True
            }

#set a default dark theme for kde
xdg_current_desktop = os.environ.get("XDG_CURRENT_DESKTOP")
if xdg_current_desktop == "KDE":
    PARAMS['theme'] = 'dark'

APP = 'slimbook'
VERSION = '0.6'
APPCONF = APP + '.conf'
APPDATA = APP + '.data'
APPNAME = 'Slimbook Service'
CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.config')
CONFIG_APP_DIR = os.path.join(CONFIG_DIR, APP)
CONFIG_FILE = os.path.join(CONFIG_APP_DIR, APPCONF)
DATA_FILE = os.path.join(CONFIG_APP_DIR, APPDATA)
AUTOSTART_DIR = os.path.join(CONFIG_DIR, 'autostart')
FILE_AUTO_START = os.path.join(AUTOSTART_DIR,
                               'slimbook-client-autostart.desktop')
                               
SLB_FEED_URL = "https://github.com/Slimbook-Team/slimbook-notifications-feed/raw/main/slb-rss-{0}.xml"
SLB_CACHE_PATH = os.path.expanduser("~/.cache/slimbook-service/")

SLB_IPC_PATH = "/var/run/slimbook-service.socket"

def is_package():
    return os.path.abspath(os.path.dirname(__file__)).startswith('/usr')

if is_package():
    APPDIR = '/usr/share/slimbook'
else:
    APPDIR = os.path.abspath(os.path.join('..', os.path.dirname(os.path.realpath(__file__))))

LANGDIR = os.path.join(APPDIR, 'locale-langpack')
ICONDIR = os.path.join(APPDIR, 'icons')
FILE_AUTO_START_ORIG = os.path.join(APPDIR,
                                    'slimbook-client-autostart.desktop')

ICONDIR = os.path.join(APPDIR, 'icons')
ICON = os.path.join(ICONDIR, 'slimbook_be1ofus_light.svg')

STATUS_ICON = {}
STATUS_ICON['light'] = (os.path.join(ICONDIR, 'slimbook-status-active-light.svg'))
STATUS_ICON['light-attention'] = (os.path.join(ICONDIR, 'slimbook-status-attention-light.svg'))
STATUS_ICON['dark'] = (os.path.join(ICONDIR, 'slimbook-status-active-dark.svg'))
STATUS_ICON['dark-attention'] = (os.path.join(ICONDIR, 'slimbook-status-attention-dark.svg'))

INFO_UPTIME = _("Uptime")
INFO_MEM = _("Memory Free/Total")
INFO_MEM_DEVICE = _("Memory device")
INFO_DISK_DEVICE = _("Disk Free/Total")
INFO_KERNEL = _("Kernel")
INFO_OS = _("OS")
INFO_DESKTOP = _("Desktop")
INFO_SESSION = _("Session")
INFO_PRODUCT = _("Product")
INFO_SERIAL = _("Serial")
INFO_BIOS = _("Bios Version")
INFO_EC = _("EC Version")
INFO_BOOT = _("Boot Mode")
INFO_SB = _("Secure Boot")
INFO_CPU = _("CPU")
INFO_GPU = _("GPU")
INFO_MODULE = _("Module loaded")
INFO_FN_LOCK = _("Fn Lock")
INFO_SUPER_LOCK = _("Super Lock")
INFO_SILENT_MODE = _("Silent Mode")
INFO_TURBO_MODE = _("Turbo Mode")
INFO_PROFILE = _("Profile")

INFO_YES = _("Yes")
INFO_NO = _("No")

class Configuration(object):
    def __init__(self):
        self.params = PARAMS
        self.read()

    def get(self, key):
        try:
            return self.params[key]
        except KeyError as e:
            print(e)
            self.params[key] = PARAMS[key]
            return self.params[key]

    def set(self, key, value):
        self.params[key] = value

    def reset(self):
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        self.params = PARAMS
        self.save()

    def set_defaults(self):
        self.params = PARAMS
        self.save()

    def read(self):
        try:
            f = codecs.open(CONFIG_FILE, 'r', 'utf-8')
        except IOError as e:
            print(e)
            self.save()
            f = codecs.open(CONFIG_FILE, 'r', 'utf-8')
        try:
            self.params = json.loads(f.read())
        except ValueError as e:
            print(e)
            self.save()
        f.close()

    def save(self):
        if not os.path.exists(CONFIG_APP_DIR):
            os.makedirs(CONFIG_APP_DIR)

        f = codecs.open(CONFIG_FILE, 'w', 'utf-8')
        f.write(json.dumps(self.params, separators=(",\n", ": ")))
        f.close()

def _read_file(file):
    f = open(file,"r")
    data = f.readlines()
    f.close()
    
    return data

def _get_pciid(vendor,device):
    ret=[vendor,device]
    
    f=open("/usr/share/misc/pci.ids","r")
    lines=f.readlines()
    f.close()
    
    vm = False
    
    for line in lines:
        if not line[0]=="\t":
            if vm:
                break
            
            if vendor == line[:4]:
                ret[0]=line[6:].strip()
                vm = True
        else:
            if vm:
                if device == line[1:5]:
                    ret[1]=line[6:].strip()
    
    return ret
    
def _get_cpu():
    ret = []

    f = open("/proc/cpuinfo","r")
    lines = f.readlines()
    f.close()
    
    model = ""
    cpus = {}
    
    for line in lines:
        tmp = line.split(":")
        if (len(tmp) < 2):
            continue
        
        key = tmp[0].strip()
        value = tmp[1].strip()
        
        if (key == "model name"):
            model = value
    
        if (key == "physical id"):
            if not value in cpus:
                cpus[value] = (model,1)
            else:
                c,count = cpus[value]
                cpus[value] = (c,count + 1)
    
    for k in cpus:
        ret.append(cpus[k][0] + " x " + str(cpus[k][1]))
     
    return ret

def _get_gpu():
    gpus = []
    
    for n in range(8):
        gpu_path = "/sys/class/drm/card{0}".format(n)
        if os.path.exists(gpu_path):
            vendor = _read_file(gpu_path+"/device/vendor")[0].strip()
            device = _read_file(gpu_path+"/device/device")[0].strip()
            vendor = vendor[2:]
            device = device[2:]
            
            vendor,device = _get_pciid(vendor,device)
            
            gpus.append("{0} {1}".format(vendor,device))
    
    return gpus
    
def get_system_info():
    info = []
    
    sb_platform = slimbook.info.get_platform()
    
    uptime = slimbook.info.uptime()
    h = int(uptime / 3600)
    m = int((uptime / 60) % 60)
    s = uptime % 60
    
    txt = "{0}h {1}m {2}s".format(h,m,s)
    info.append([INFO_UPTIME,txt])
    
    try:
        data = _read_file("/proc/version")
        info.append([INFO_KERNEL,data[0].strip().split()[2]])
    except:
        pass
    
    serial=""
    memory_devices = []
    disk_devices = []
    memory = ""
    
    is_module = INFO_NO
    fn_lock = ""
    super_lock = ""
    silent_mode = ""
    profile = ""
    
    tmp = []
    
    try:
        tmp = subprocess.getstatusoutput("slimbookctl info")[1]
        tmp = tmp.split('\n')
    except:
        pass
    
    for line in tmp:
        pair = line.split(':')
        if (len(pair) == 2):
            key = pair[0]
            value = pair[1]
            
            if (key == "serial"):
                serial = value
            
            if (key == "memory device"):
                memory_devices.append(value)
            
            if (key == "disk free/total"):
                idx = value.find(" ")
                
                disk_devices.append(value[:idx] + "    " + value[idx:])
            
            if (key == "memory free/total"):
                memory = value
            
            if (key == "module loaded"):
                is_module = value.capitalize()
             
            if (key == "fn lock"):
                fn_lock = value.capitalize()
             
            if (key == "super key lock"):
                super_lock = value.capitalize()
             
            if (key == "silent mode"):
                silent_mode = value.capitalize()

            if (key == "profile"):
                profile = value.capitalize()
   
    info.append([INFO_MEM,memory])
    
    for d in disk_devices:
        info.append([INFO_DISK_DEVICE,d])
    
    try:
        if (os.path.exists("/sys/firmware/efi")):
            info.append([INFO_BOOT,"UEFI"])
            sb = False
            SB_VAR = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
            if (os.path.exists(SB_VAR)):
                f = open(SB_VAR,"rb")
                var = list(f.read())
                if (var[4] == 1):
                    sb = True
                f.close()

            if sb:
                info.append([INFO_SB,INFO_YES])
            else:
                info.append([INFO_SB,INFO_NO])
        else:
            info.append([INFO_BOOT,"Legacy"])
    except:
        pass
    
    try:
        if (os.path.exists("/usr/lib/os-release")):
            f = open("/usr/lib/os-release","rt")
            lines = f.readlines()
            f.close()

            name = None
            version = None

            for line in lines:
                tmp = line.strip().split('=')

                if (len(tmp) > 1):
                    if (tmp[0] == "NAME"):
                        name = tmp[1].strip("\"")
                    if (tmp[0] == "VERSION"):
                        version = tmp[1].strip("\"")
            if (name and version):
                info.append([INFO_OS,name + " " + version])
    except:
        pass

    try:
        info.append([INFO_DESKTOP, os.environ["XDG_CURRENT_DESKTOP"].replace(":",", ")])
    except:
        pass

    try:
        info.append([INFO_SESSION, os.environ["XDG_SESSION_TYPE"]])
    except:
        pass
    
    try:
        data = _read_file("/sys/class/dmi/id/product_name")
        info.append([INFO_PRODUCT,data[0].strip()])
    except:
        pass
    
    try:
        data = _read_file("/sys/class/dmi/id/bios_version")
        info.append([INFO_BIOS,data[0].strip()])
    except:
        pass
    
    try:
        data = _read_file("/sys/class/dmi/id/ec_firmware_release")
        info.append([INFO_EC,data[0].strip()])
    except:
        pass
    
    info.append([INFO_SERIAL,serial])

    try:
        for cpu in _get_cpu():
            info.append([INFO_CPU, cpu])
    except:
        pass
    
    try:
        for gpu in _get_gpu():
            info.append([INFO_GPU,gpu])
    except:
        pass
        
    for m in memory_devices:
        info.append([INFO_MEM_DEVICE,m])
    
        
    if (sb_platform != 0 ):
        info.append([INFO_MODULE,is_module])
        
        if (sb_platform == slimbook.info.SLB_PLATFORM_QC71):
            info.append([INFO_FN_LOCK,fn_lock])
            info.append([INFO_SUPER_LOCK,super_lock])
            info.append([INFO_PROFILE,profile])
    
    return info

def get_lang():
    lang = locale.getlocale()[0]
    lang = lang.split("_")[0]
    
    if not lang in ["en","es"]:
        lang = "en"
        
    return lang

def download_feed():
    os.makedirs(SLB_CACHE_PATH,exist_ok = True)

    lang = get_lang()
    #print(SLB_FEED_URL.format(lang))
    r = requests.get(SLB_FEED_URL.format(lang), allow_redirects = True)

    path = SLB_CACHE_PATH + "/sb-rss.xml"
    f = open(path,"wb")
    f.write(r.content)
    f.close()

def report_proc(self, glib_cb, cb, report_type):
        proc = subprocess.Popen(["slimbookctl", report_type], stdout= subprocess.PIPE, stderr= subprocess.PIPE)

        cb_args = [False, ""]

        while(proc.poll() != 0 and proc.poll() == None):
            glib_cb(cb, cb_args)  

        try:
            o = proc.communicate(timeout = 5) 
        except TimeoutExpired:
            proc.kill()
            o = proc.communicate()
            
        if re.search("\/.*", o[0].decode("utf-8")):
            cb_args.pop(1)
            path = re.search("\/.*", o[0].decode("utf-8")).group(0)
            cb_args.append(path)

        cb_args.pop(0)
        cb_args.insert(0, True)

        glib_cb(cb, cb_args)  

        subprocess.Popen(["xdg-open", (cb_args[1])[:-7]])
