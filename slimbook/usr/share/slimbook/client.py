#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 Lorenzo Carbonell <a.k.a. atareao>

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import dbus
import zmq
import logging
import threading
import gi
try:
    gi.require_version('Gtk', '3.0')
    gi.require_version('AppIndicator3', '0.1')
except Exception as e:
    print(e)
    exit(1)
from gi.repository import AppIndicator3 as appindicator
from gi.repository import Gtk
from gi.repository import GObject

#import slimbook_service_indicator

PORT = "8998"

# Socket to talk to server
context = zmq.Context()
socket = context.socket(zmq.SUB)

print("Collecting updates from weather server...")
socket.connect(f"tcp://localhost:{PORT}")

# Subscribe to zipcode, default is NYC, 10001
socket.setsockopt_string(zmq.SUBSCRIBE, "")


obj = dbus.SessionBus().get_object("org.freedesktop.Notifications",
                                   "/org/freedesktop/Notifications")
obj = dbus.Interface(obj, "org.freedesktop.Notifications")


logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] (%(threadName)-10s) %(message)s',
)


class SlimbookServiceIndicator:
    def __init__(self):
        self.indicator = appindicator.Indicator.new('SlimbookServiceIndicator',
                                                    '',
                                                    appindicator.
                                                    IndicatorCategory.
                                                    HARDWARE)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE)
        self.running = True
        self.client = threading.Thread(name='my_service', target=self.watch_client)
        self.client.start()

    def watch_client(self):
        logging.debug('Launching client...')
        while self.running:
            data = socket.recv_json()
            print(data)
            self.message("Slimbook Service", data["msg"])
        logging.debug('Exiting')

    def message(self, title, message):
        # os.system(f"notify-send '{title}' '{message}' -t 1")
        obj.Notify("Slimbook Service", int(1845665481), "",
                   title, message, [], {"urgency": 1}, 1000)

def main():
    if dbus.SessionBus().request_name(
        'es.slimbok.SlimbookServiceIndicator') !=\
            dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER:
        print("application already running")
        exit(0)
    SlimbookServiceIndicator()
    Gtk.main()


if __name__ == "__main__":
    main()
