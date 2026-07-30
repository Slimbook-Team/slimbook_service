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
import time
import logging

logger = logging.getLogger("slimbook.touchpad")

BUTTON_SWITCH_USAGE_ID = (iohid.HID_USAGE_PAGE_DIGITIZER << 16) | iohid.HID_USAGE_DIGITIZER_BUTTON_SWITCH
SURFACE_SWITCH_USAGE_ID = (iohid.HID_USAGE_PAGE_DIGITIZER << 16) | iohid.HID_USAGE_DIGITIZER_SURFACE_SWITCH

class Touchpad:
    MODE_UNKNOWN = 0
    MODE_HIDRAW = 1
    MODE_EVDEV = 2

    STATE_UNKNOWN = 0
    STATE_LOCKED = 1
    STATE_UNLOCKED = 2
    # Partially locked: one of the two switches is off. The right corner button
    # of some touchpads leaves the device in a state like this, and treating it
    # as "unlocked" is what makes that button stop working (see get_state).
    STATE_PARTIAL = 3

    # Bits of the feature report, in the order they are declared in the report
    # descriptor: surface switch first, button switch second. A bit set means
    # the corresponding function is enabled.
    SURFACE_BIT = 0x01
    BUTTON_BIT = 0x02
    ALL_BITS = SURFACE_BIT | BUTTON_BIT

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
                try:
                    self.get_state()
                    return
                except:
                    #some devices fails with a errno 22 (Invalid Argument)
                    #better to fallback to evdev grab method
                    found = False
    
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
                
    def _find_i2c_device(self):
        """Locate the i2c device backing this hidraw fd, and its driver.

        Returns (device_name, driver_path) or (None, None). Everything is
        derived from the file descriptor, so no device name is hardcoded: the
        hidraw number, the i2c device name and the driver all vary per model.
        """
        if self.mode != Touchpad.MODE_HIDRAW or self.fd <= 0:
            return None, None
        try:
            st = os.fstat(self.fd)
            path = os.path.realpath("/sys/dev/char/{0}:{1}".format(
                os.major(st.st_rdev), os.minor(st.st_rdev)))
        except OSError:
            return None, None

        # Walk up until the i2c device that owns the HID device is found.
        while path not in ("/", "/sys", ""):
            driver_link = os.path.join(path, "driver")
            subsystem_link = os.path.join(path, "subsystem")
            if os.path.islink(driver_link) and os.path.islink(subsystem_link):
                try:
                    subsystem = os.path.basename(os.path.realpath(subsystem_link))
                    driver = os.path.realpath(driver_link)
                except OSError:
                    return None, None
                if subsystem == "i2c":
                    return os.path.basename(path), driver
            path = os.path.dirname(path)
        return None, None

    def _rebind_driver(self):
        """Re-attach the i2c-hid driver, restoring the touchpad's own gestures.

        Why this is needed: after the feature report is written, the firmware of
        at least the ProX/Executive touchpad stops handling its own gestures --
        the double tap and the right corner button go dead. Re-binding the
        driver re-initialises the device and brings them back. This is what made
        "Trackpad lock" break the right corner button.

        Note the firmware also resets the feature to "unlocked" when it comes
        back, so this must only be done when unlocking; doing it after locking
        would undo the lock.

        Requires root, which the service already has. Failure is not fatal: the
        touchpad keeps working, only its gestures stay unresponsive.
        """
        device, driver = self._find_i2c_device()
        if not device or not driver:
            logger.debug("could not locate the i2c device, skipping rebind")
            return False

        try:
            with open(os.path.join(driver, "unbind"), "w") as f:
                f.write(device)
            with open(os.path.join(driver, "bind"), "w") as f:
                f.write(device)
        except OSError as e:
            logger.warning("could not rebind {0}: {1}".format(device, e))
            return False

        # The old fd points to a device that no longer exists.
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = 0
        self.mode = Touchpad.MODE_UNKNOWN

        # Wait for udev to recreate the node before re-opening. Re-opening too
        # early would find no hidraw device and fall back to the evdev grab
        # method, which loses the hardware lock and the LED -- exactly what this
        # code path exists to preserve. Measured: the node is back in ~0.3 s.
        for attempt in range(30):
            time.sleep(0.05)
            self.__init__()
            if self.mode == Touchpad.MODE_HIDRAW:
                logger.info("touchpad driver rebound, hardware gestures restored")
                return True

        logger.warning("touchpad did not come back as hidraw after rebinding")
        return False

    def _set_bits(self, value):
        iohid.set_feature(self.fd, self.report_id, bytes([value & Touchpad.ALL_BITS]))

    def lock(self):
        if self.mode == Touchpad.MODE_HIDRAW and self.fd>0:
            self._set_bits(0x00)

        if self.mode == Touchpad.MODE_EVDEV and self.device:
            self.device.grab()
            self.state = Touchpad.STATE_LOCKED

    def unlock(self):
        if self.mode == Touchpad.MODE_HIDRAW and self.fd>0:
            self._set_bits(Touchpad.ALL_BITS)
            # Give the touchpad its own gestures back. Only on unlock: the
            # firmware resets the feature to unlocked on re-init.
            self._rebind_driver()

        if self.mode == Touchpad.MODE_EVDEV and self.device:
            self.device.ungrab()
            self.state = Touchpad.STATE_UNLOCKED

    def toggle(self):
        self.get_state()

        if (self.mode == Touchpad.MODE_HIDRAW and self.fd>0) or (self.mode == Touchpad.MODE_EVDEV and self.device):
            if self.state == Touchpad.STATE_UNLOCKED:
                self.lock()
            else:
                # Locked, partially locked or unknown: unlock. Going to a known
                # good state is always safer than locking further, and it means
                # a partial lock can be cleared with the same action.
                self.unlock()

    def get_state(self):

        if self.mode == Touchpad.MODE_HIDRAW and self.fd>0:
            self.state = Touchpad.STATE_UNKNOWN
            # mask is hardcoded, in the future maybe would be
            # better to obtain it from report descriptor
            data = int(self.get_bits()) & Touchpad.ALL_BITS

            if data == 0:
                self.state = Touchpad.STATE_LOCKED
            elif data == Touchpad.ALL_BITS:
                self.state = Touchpad.STATE_UNLOCKED
            else:
                # Exactly one switch is off. Previously this branch was folded
                # into STATE_UNLOCKED, which meant the state was overwritten
                # with 0x00 or 0x03 on the next toggle and the partial lock was
                # lost.
                self.state = Touchpad.STATE_PARTIAL

        return self.state

    def get_bits(self):
        """Raw value of the two switch bits, or 0 if not available."""
        if self.mode != Touchpad.MODE_HIDRAW or self.fd <= 0:
            return 0
        # This ioctl intermittently fails with EINVAL on some devices. It is
        # worth retrying: falling back to the evdev grab method loses the
        # hardware lock, and with it the touchpad LED.
        for attempt in range(4):
            try:
                return int(iohid.get_feature(self.fd, self.report_id, 1)[0])
            except OSError as e:
                if e.errno != 22 or attempt == 3:
                    raise
                time.sleep(0.01)
        return 0

    def valid(self):
        return (self.mode != Touchpad.MODE_UNKNOWN)
