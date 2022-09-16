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

import dbus
import dbus.service
import zmq
import logging
import threading
import gi
import os
import sys
import shutil
import common
import webbrowser
try:
    gi.require_version('Gtk', '3.0')
    gi.require_version('GLib', '2.0')
    gi.require_version('GdkPixbuf', '2.0')
    gi.require_version('Notify', '0.7')

    try:
        gi.require_version('AyatanaAppIndicator3', '0.1')
        from gi.repository import AyatanaAppIndicator3 as appindicator
    except:
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import AppIndicator3 as appindicator
except Exception as e:
    print(e)
    exit(1)

from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import GdkPixbuf
from gi.repository import Notify
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from optparse import OptionParser
from common import Configuration
from common import _

BUS_NAME = 'es.slimbok.SlimbookServiceIndicator'
BUS_PATH = '/es/slimbok/SlimbookServiceIndicator'

Notify.init("Slimbok Client Notifications")
notification = Notify.Notification.new('', '' )
notification.set_app_name("Slimbok Client Notifications")
notification.set_timeout(Notify.EXPIRES_DEFAULT)
notification.set_urgency(Notify.Urgency.CRITICAL)

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] (%(threadName)-10s) %(message)s',
)


class SlimbookServiceIndicator(dbus.service.Object):
    def __init__(self):
        bus = dbus.SessionBus()
        if bus.request_name(BUS_NAME, dbus.bus.NAME_FLAG_DO_NOT_QUEUE) == dbus.bus.REQUEST_NAME_REPLY_EXISTS:
            logging.debug(
                "D-Bus Service is already running.\nThe MainLoop will close...")

            GLib.MainLoop().quit()
            raise Exception("D-Bus Service is already running.")

        bus_name = dbus.service.BusName(BUS_NAME, bus)
        # print(bus_name)
        dbus.service.Object.__init__(self, bus_name, BUS_PATH)

        self.set_indicator()
        Notify.init('Slimbook')

    def set_indicator(self):

        logging.debug("Setting indicator...")
        self.active_icon = None
        self.about_dialog = None
        self.active = False
        self.notification = Notify.Notification.new('', '', None)
        self.read_preferences()
        manage_autostart(self.autostart)

        self.indicator = appindicator.Indicator.new('SlimbookServiceIndicator',
                                                    self.active_icon,
                                                    appindicator.
                                                    IndicatorCategory.
                                                    HARDWARE)

        self.running = True
        self.client = threading.Thread(
            name='my_service', target=self.watch_client)
        self.client.daemon = True
        self.client.start()

        menu = self.get_menu()
        self.indicator.set_menu(menu)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE) if self.show else self.indicator.set_status(
            appindicator.IndicatorStatus.PASSIVE)

    def watch_client(self):
        PORT = "8999"

        # Socket to talk to server
        context = zmq.Context()
        socket = context.socket(zmq.SUB)

        logging.debug(
            "Collecting event notifications from slimbook service...")
        socket.connect(f"tcp://localhost:{PORT}")

        # Subscribe to zipcode, default is NYC, 10001
        socket.setsockopt_string(zmq.SUBSCRIBE, "")

        logging.debug('Launching client...')
        while self.running:
            data = socket.recv_json()
            logging.debug(data)
            self.message("Slimbook Service", data["msg"])
        logging.debug('Exiting')

    def message(self, title, message):
        notification.update(title, message, 'dialog-information')
        notification.show()

    def read_preferences(self):
        configuration = Configuration()
        self.first_time = configuration.get('first-time')
        self.autostart = configuration.get('autostart')
        self.version = configuration.get('version')
        self.theme = configuration.get('theme')
        self.active_icon = os.path.abspath(
            common.STATUS_ICON[configuration.get('theme')])
        self.show = configuration.get('show')

    def get_menu(self):
        """Create and populate the menu."""
        menu = Gtk.Menu()

        separator1 = Gtk.SeparatorMenuItem()
        separator1.show()
        menu.append(separator1)
        #
        menu_preferences = Gtk.MenuItem.new_with_label(_('Preferences'))
        menu_preferences.connect('activate', self.on_preferences_item)
        menu_preferences.show()
        menu.append(menu_preferences)

        about_item = Gtk.MenuItem.new_with_label(_('About'))
        about_item.connect('activate', self.on_about_item)
        about_item.show()
        separator = Gtk.SeparatorMenuItem()
        separator.show()
        menu.append(separator)
        menu.append(about_item)

        bug_item = Gtk.MenuItem(label=_(
            'Report a bug...'))
        bug_item.connect(
            'activate', lambda x: webbrowser.open(
                'https://github.com/slimbook/slimbook_service/issues/new'))
        bug_item.show()
        menu.append(bug_item)
        #
        separator2 = Gtk.SeparatorMenuItem()
        separator2.show()
        menu.append(separator2)
        #
        menu_exit = Gtk.MenuItem.new_with_label(_('Exit'))
        menu_exit.connect('activate', self.on_quit_item)
        menu_exit.show()
        menu.append(menu_exit)
        #
        menu.show()
        return(menu)

    def get_about_dialog(self):
        """Create and populate the about dialog."""
        about_dialog = Gtk.AboutDialog()
        about_dialog.set_name(common.APPNAME)
        about_dialog.set_version(common.VERSION)
        about_dialog.set_copyright(
            'Copyrignt (c) 2022\nSlimbook')
        about_dialog.set_comments(_('Slimbook Service'))
        about_dialog.set_license('''
This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.
''')
        about_dialog.set_website('http://www.slimbook.es')
        about_dialog.set_website_label('Visit Website')
        link = Gtk.LinkButton(uri=(
            'https://github.com/slimbook/slimbook_service/issues/new'), label=(_('Report issue')))
        link.set_name('link')
        link.set_halign(Gtk.Align.CENTER)
        about_dialog.set_authors([
            'Slimbook <dev@slimbook.es>'])
        about_dialog.set_documenters([
            'Slimbook <dev@slimbook.es>'])
        about_dialog.set_translator_credits('Slimbook <dev@slimbook.es>')
        size = 125
        about_dialog.set_icon(GdkPixbuf.Pixbuf.new_from_file_at_scale(
            common.ICON, size, size, True))
        about_dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file_at_scale(
            common.ICON, size, size, True))
        about_dialog.set_program_name(common.APPNAME)
        return about_dialog

    def on_preferences_item(self, widget, data=None):
        widget.set_sensitive(False)
        preferences_dialog = PreferencesDialog()
        if preferences_dialog.run() == Gtk.ResponseType.ACCEPT:
            preferences_dialog.close_ok()
            self.read_preferences()
        preferences_dialog.hide()
        preferences_dialog.destroy()
        self.indicator.set_icon(self.active_icon)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE) if self.show else self.indicator.set_status(
            appindicator.IndicatorStatus.PASSIVE)
        widget.set_sensitive(True)

    def on_quit_item(self, widget, data=None):
        Notify.uninit()
        logging.debug('Exit')
        exit(0)

    def on_about_item(self, widget, data=None):
        if self.about_dialog:
            self.about_dialog.present()
        else:
            self.about_dialog = self.get_about_dialog()
            self.about_dialog.run()
            self.about_dialog.destroy()
            self.about_dialog = None

    # Interface and Method

    @dbus.service.method(BUS_NAME)
    def show_preferences(self):

        preferences_dialog = PreferencesDialog()
        if preferences_dialog.run() == Gtk.ResponseType.ACCEPT:
            preferences_dialog.close_ok()
            self.read_preferences()
        preferences_dialog.hide()
        preferences_dialog.destroy()
        self.indicator.set_icon(self.active_icon)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE) if self.show else self.indicator.set_status(
            appindicator.IndicatorStatus.PASSIVE)


class PreferencesDialog(Gtk.Dialog):
    def __init__(self):
        Gtk.Dialog.__init__(self, 'Slimbook ' + _('Preferences'),
                            None,
                            modal=True,
                            destroy_with_parent=True
                            )

        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.REJECT,
                         Gtk.STOCK_OK, Gtk.ResponseType.ACCEPT)
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        # self.set_size_request(400, 230)
        self.connect('close', self.close_application)
        self.set_icon(GdkPixbuf.Pixbuf.new_from_file_at_scale(
            common.ICON, 64, 64, True))

        vbox0 = Gtk.VBox(spacing=5)
        vbox0.set_border_width(20)
        self.get_content_area().add(vbox0)
        table1 = Gtk.Table(n_columns=8, n_rows=2, homogeneous=False)
        vbox0.pack_start(table1, False, True, 1)

        label0 = Gtk.Label(label=_('Show indicator') + ':')
        label0.set_halign(Gtk.Align.CENTER)
        table1.attach(label0, 0, 1, 6, 7, xpadding=15, ypadding=15)
        self.switch0 = Gtk.Switch()
        table1.attach(self.switch0, 1, 2, 6, 7, xpadding=15, ypadding=15,
                      xoptions=Gtk.AttachOptions.SHRINK)

        label1 = Gtk.Label(label=_('Autostart') + ':')
        label1.set_halign(Gtk.Align.CENTER)
        table1.attach(label1, 0, 1, 7, 8, xpadding=15, ypadding=15)
        self.switch1 = Gtk.Switch()
        table1.attach(self.switch1, 1, 2, 7, 8, xpadding=15, ypadding=15,
                      xoptions=Gtk.AttachOptions.SHRINK)
        label2 = Gtk.Label(label=_('Icon light') + ':')
        label2.set_halign(Gtk.Align.CENTER)
        table1.attach(label2, 0, 1, 8, 9, xpadding=15, ypadding=15)
        self.switch2 = Gtk.Switch()
        table1.attach(self.switch2, 1, 2, 8, 9, xpadding=15, ypadding=15,
                      xoptions=Gtk.AttachOptions.SHRINK)
        #
        self.load_preferences()
        #
        self.show_all()

    def close_application(self, widget, event):
        self.hide()

    def close_ok(self):
        self.save_preferences()

    def load_preferences(self):
        configuration = Configuration()
        first_time = configuration.get('first-time')
        version = configuration.get('version')
        if first_time or version != common.VERSION:
            configuration.set_defaults()
            configuration.read()

        self.switch0.set_active(configuration.get('show') == True)
        self.switch1.set_active(os.path.exists(common.FILE_AUTO_START))
        self.switch2.set_active(configuration.get('theme') == 'light')

    def save_preferences(self):

        configuration = Configuration()
        configuration.set('first-time', False)
        configuration.set('version', common.VERSION)
        configuration.set('show', self.switch0.get_active())

        manage_autostart(self.switch1.get_active())
        if self.switch2.get_active():
            configuration.set('theme', 'light')
        else:
            configuration.set('theme', 'dark')
        configuration.save()


def manage_autostart(create):
    if not os.path.exists(common.AUTOSTART_DIR):
        os.makedirs(common.AUTOSTART_DIR)
    if create:
        if not os.path.exists(common.FILE_AUTO_START):
            shutil.copyfile(common.FILE_AUTO_START_ORIG,
                            common.FILE_AUTO_START)
    else:
        if os.path.exists(common.FILE_AUTO_START):
            os.remove(common.FILE_AUTO_START)


def preferences():
    try:
        init_indicator()

    except:
        bus = dbus.SessionBus()
        session = bus.get_object(BUS_NAME, BUS_PATH)
        show_preferences = session.get_dbus_method(
            'show_preferences', BUS_NAME)
        # Call the methods with their specific parameters
        show_preferences()


def init_indicator():
    DBusGMainLoop(set_as_default=True)
    dbus_service = SlimbookServiceIndicator()
    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        logging.debug("\nThe MainLoop will close...")
        GLib.MainLoop().quit()


def main():
    if len(sys.argv) > 1:
        usage_msg = ('usage: %prog [options]')
        parser = OptionParser(usage=usage_msg, add_help_option=False)
        parser.add_option('-h', '--help',
                          action='store_true',
                          dest='help',
                          default=False,
                          help=('show this help and exit.'))
        parser.add_option('-p', '--preferences',
                          action='store_true',
                          dest='preferences',
                          default=False,
                          help=('show preferences.'))
        (options, args) = parser.parse_args()
        if options.help:
            parser.print_help()
        elif options.preferences:
            preferences()

        exit(0)
    else:
        logging.debug("Try Indicator init")
        init_indicator()


if __name__ == "__main__":
    main()
