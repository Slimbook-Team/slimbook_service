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

from common import Configuration
from common import _

import slimbook.info

#import dbus
#import dbus.service
import zmq
import logging
import threading
import gi
import os
import sys
import shutil
import common
import webbrowser
import feedparser
import hashlib
import time
import signal
import fnmatch

try:
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gio', '2.0')
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

from gi.repository import GObject
from gi.repository import Gtk,Gdk,Gio
from gi.repository import GLib
from gi.repository import GdkPixbuf
from gi.repository import Notify
#from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from optparse import OptionParser


BUS_NAME = 'es.slimbook.ServiceIndicator'
BUS_PATH = '/es/slimbook/ServiceIndicator'

Notify.init("Slimbok Client Notifications")
notification = Notify.Notification.new('', '' )
notification.set_app_name("Slimbok Client Notifications")
notification.set_timeout(Notify.EXPIRES_DEFAULT)
notification.set_urgency(Notify.Urgency.CRITICAL)

dbus_service = None

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] (%(threadName)-10s) %(message)s',
)

class Feed:

    def __init__(self, entry):
        try:

            m = hashlib.md5()
            m.update(str(entry).encode())
            
            self.id = m.hexdigest()
            self.title = entry.title
            self.body = entry.description
            self.link = entry.get("link")
            #print("link:",entry.get("link"))
            self.tags = []
            self.icon = "dialog-information"
            
            self.cached = False
            
            if (entry.get("tags")):
                for tag in entry.tags:
                    term = tag.get("term")
                    
                    if (term):
                        self.tags.append(term)
                    
                        if (term == "firmware"):
                            self.icon = "application-x-firmware"
            
        except Exception as e:
            print(e)

def load_cache_feeds():
    feeds = []
    
    try:
        cache_file = os.path.expanduser("~/.cache/slimbook-service/feeds.dat")
        f = open(cache_file,"r")
        for line in f.readlines():
            value = line.strip()
            feeds.append(value)
        f.close()
    except:
        pass
    
    return feeds
    
def store_cache_feeds(feeds):
    try:
        cache_path = os.path.expanduser("~/.cache/slimbook-service/")
        os.makedirs(cache_path,exist_ok = True)
    
        f = open(cache_path+"feeds.dat","w")
        for feed in feeds:
            f.write(feed.id+"\n")
        
        f.close()
    except Exception as e:
        print(e)

def check_time_feeds():
    feed = os.path.expanduser("~/.cache/slimbook-service/sb-rss.xml")
    
    if os.path.exists(feed):
        mtime = os.path.getmtime(feed)
        now = time.time()
        return (now - mtime) < (3600*24)
    else:
        return False

def check_news():
    
    news = []
    
    cached = load_cache_feeds()
    
    product = slimbook.info.product_name().lower()
    print(product)
    
    try:
        feed = feedparser.parse(os.path.expanduser("~/.cache/slimbook-service/sb-rss.xml"))
    
        for entry in feed["entries"]:
            nw = Feed(entry)
            
            ignore = False
            for tag in nw.tags:
                if (tag.startswith("model:")):
                    target=tag.split(":")[1]
                    print(target)
                    if (not fnmatch.fnmatch(product,target)):
                        logging.info("feed ignored by filter:{0}!={1}".format(product,target))
                        ignore = True
                    else:
                        ignore = False
            
            if (ignore):
                continue
                
            for cid in cached:
                if cid == nw.id:
                    print("id cached:",nw.id)
                    nw.cached = True
                    break
                    
            news.append(nw)
            
            body = nw.body
            
            if (nw.link):
                body = body + " " + nw.link
            
            if (nw.cached == False):
                nt = Notify.Notification.new(nw.title, body, nw.icon)
                nt.show()
        
        store_cache_feeds(news)
        
            
    except Exception as e:
        print(e)
        
    return news

class ServiceIndicator(Gio.Application):
    def __init__(self):
        super().__init__(application_id="slimbook.service",flags=Gio.ApplicationFlags.IS_SERVICE)
        xml = f"""
            <node>
              <interface name='es.slimbook.ServiceIndicator'>
                  <method name='ShowPreferences'/>
              </interface>
            </node>
            """
        self.node = Gio.DBusNodeInfo.new_for_xml(xml)
         
        self.bus = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT,
            None,
            self.on_name_acquired,
            None)
        
        GObject.signal_new('preferences-close', PreferencesDialog, GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,))
        
        GObject.signal_new('feed-update-start', ServiceIndicator, GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,))
        
        GObject.signal_new('feed-update-complete', ServiceIndicator, GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,))
        
        #set up zmq
        context = zmq.Context()
        self.socket = context.socket(zmq.SUB)
        self.socket.connect("ipc://{0}".format(common.SLB_IPC_PATH))
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        
        GLib.idle_add(self.zmq_loop)
        
        self.set_indicator()
        Notify.init('Slimbook')
        
        GLib.timeout_add_seconds(5,self.on_initial_check)
        
        self.feed_updating = False
        
    def on_name_acquired(self, connection, name):
    
        connection.register_object(
            BUS_PATH,
            self.node.interfaces[0],
            self.on_message,
            None,
            None)
     
    def on_message(self,connection, sender, path, interface, method, params, invo):
        if (method == "ShowPreferences"):
            self.show_preferences()
            invo.return_value(None)
    
    def zmq_loop(self):
    
        while self.poller.poll(timeout = 50):
            data = self.socket.recv_json()
            self.message("slimbook",data["msg"])
        
        return True
    
    def on_initial_check(self):
        if (not check_time_feeds()):
            self.update_feed()
        
        return False
        
    def update_feed(self):
        print("updating feed...")
        
        if self.feed_updating == False:
            self.emit('feed-update-start', False)
            self.feed_updating = True
            thread = threading.Thread(target = self.update_feed_worker)
            thread.daemon = True
            thread.start()
    
    def update_feed_worker(self):
        common.download_feed()
        GLib.idle_add(self.on_feed_update)
    
    def on_feed_update(self):
        logging.info("feed has been updated")
        self.feed_updating = False
        self.emit("feed-update-complete", False)
    
    def set_indicator(self):

        logging.debug("Setting indicator...")
        self.active_icon = None
        self.about_dialog = None
        self.active = False
        
        self.notification = Notify.Notification.new('', '', None)
        self.read_preferences()
        manage_autostart(self.autostart)

        self.indicator = appindicator.Indicator.new('com.slimbook.service',
                                                    self.active_icon,
                                                    appindicator.
                                                    IndicatorCategory.
                                                    HARDWARE)
        
        self.indicator.set_title('Slimbook Client Notifications')

        self.running = True
        
        self.menu = self.get_menu()
        self.indicator.set_menu(self.menu)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE) if self.show else self.indicator.set_status(
            appindicator.IndicatorStatus.PASSIVE)

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

        self.menu_preferences = Gtk.MenuItem.new_with_label(_('Preferences'))
        self.menu_preferences.connect('activate', self.on_preferences_item)
        self.menu_preferences.show()
        menu.append(self.menu_preferences)
        
        menu_sysinfo = Gtk.MenuItem.new_with_label(_('System information'))
        menu_sysinfo.connect('activate', self.on_sysinfo_item)
        menu_sysinfo.show()
        menu.append(menu_sysinfo)
        
        self.menu_news = Gtk.MenuItem.new_with_label(_('News'))
        self.menu_news.connect('activate', self.on_news_item)
        self.menu_news.show()
        menu.append(self.menu_news)
        
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
        
        separator2 = Gtk.SeparatorMenuItem()
        separator2.show()
        menu.append(separator2)
        
        menu_exit = Gtk.MenuItem.new_with_label(_('Exit'))
        menu_exit.connect('activate', self.on_quit_item)
        menu_exit.show()
        menu.append(menu_exit)
        
        menu.show()

        return(menu)

    def get_about_dialog(self):
        """Create and populate the about dialog."""
        about_dialog = Gtk.AboutDialog()
        about_dialog.set_name(common.APPNAME)
        about_dialog.set_version(common.VERSION)
        about_dialog.set_copyright(
            'Copyrignt (c) 2024\nSlimbook')
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
        self.show_preferences()
        
    def on_sysinfo_item(self, widget, data=None):
        logging.debug("system info")
        widget.set_sensitive(False)
        info = common.get_system_info()
        
        sysinfo_dialog = SystemInfoDialog(info)
        sysinfo_dialog.run()
        sysinfo_dialog.destroy()
        widget.set_sensitive(True)
    
    def on_news_item(self, widget, data = None):
        logging.debug("news")
        widget.set_sensitive(False)
        news_dialog = NewsDialog(self)
        news_dialog.connect('delete-event', self.on_news_delete_event)
    
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

    def on_news_delete_event(self, window, event):
        self.menu_news.set_sensitive(True)
    
    def on_preferences_close(self, *args):
        self.menu_preferences.set_sensitive(True)
        print(args)
        #self.indicator.set_icon(self.active_icon)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE) if self.show else self.indicator.set_status(
            appindicator.IndicatorStatus.PASSIVE)

    def show_preferences(self):
        self.menu_preferences.set_sensitive(False)
        preferences_dialog = PreferencesDialog()
        preferences_dialog.connect("preferences-close",self.on_preferences_close)
        
class PreferencesDialog(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self)
        self.set_modal(True)
        
        self.connect('delete-event',self.on_delete_event)
        
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_icon(GdkPixbuf.Pixbuf.new_from_file_at_scale(
            common.ICON, 64, 64, True))

        header = Gtk.HeaderBar()
        header.set_title('Slimbook ' + _('Preferences'))
        header.set_show_close_button(True)
        
        self.btn_save = Gtk.Button.new_with_label(_("Save"))
        self.btn_save.set_sensitive(False) 
        header.pack_end(self.btn_save)
        self.set_titlebar(header)

        vbox0 = Gtk.VBox(spacing=5)
        vbox0.set_border_width(20)
        self.add(vbox0)
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
        
        self.load_preferences()
        
        self.changes = False
        self.switch0.connect('state-set',self.on_switch_state_set)
        self.switch1.connect('state-set',self.on_switch_state_set)
        self.switch2.connect('state-set',self.on_switch_state_set)
        
        self.show_all()

    def on_switch_state_set(self, switch, state):
        self.btn_save.set_sensitive(True)
        self.changes = True
    
    def on_delete_event(self, window, event):
        self.emit('preferences-close', self.changes)
        return False
    
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


class SystemInfoDialog(Gtk.Dialog):

    def __init__(self,info):
        Gtk.Dialog.__init__(self, 'Slimbook ' + _('System information'),
                            None,
                            modal=True,
                            destroy_with_parent=True,
                            use_header_bar=True
                            )
                            
        CSS = '''
            list {
                border-width: 1px;
                border-style: inset;
                border-color: lightgrey;
            }
            
            row {
                border-width: 1px;
                border-style: outset;
                border-color: lightgrey;
                min-height: 32px;
                min-width: 400px;
            }
            '''
        
        self.info = info
        
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        style_context = self.get_style_context()
        style_context.add_provider_for_screen(
                self.get_screen(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        #btn_copy = Gtk.Button(label=_("Copy"))
        btn_copy = Gtk.Button.new_from_icon_name("edit-copy",Gtk.IconSize.BUTTON)
        btn_copy.connect("clicked",self.btn_copy_clicked)
        self.get_header_bar().pack_end(btn_copy)
        
        vbox = Gtk.VBox(spacing = 12)
        listbox = Gtk.ListBox()
        
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        
        self.get_content_area().add(vbox)
        vbox.pack_start(listbox,False,False,1)
        vbox.set_border_width(16)
        
        for k in info:
            key = k[0]
            value = k[1]
            label_key = Gtk.Label()
            label_key.set_markup("<b>{0}</b>".format(key))
            label_value = Gtk.Label(label=value)
            
            hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
            
            hbox.pack_start(label_key, False, False, 1)
            hbox.pack_end(label_value, False, False, 1)
            
            row = Gtk.ListBoxRow()
            row.add(hbox)
            
            listbox.add(row)
        
        self.show_all()
        
    def btn_copy_clicked(self,button):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        
        txt=""
        for k in self.info:
            key = k[0]
            value = k[1]
            txt=txt+"{0}:\t{1}\n".format(key,value)
        
        clipboard.set_text(txt,-1)
        button.set_sensitive(False)

class NewsDialog(Gtk.Window):

    def __init__(self, parent):
        Gtk.Window.__init__(self)
        self.set_modal(True)
        self.parent = parent
        
        CSS = '''
            list {
                border-width: 1px;
                border-style: inset;
                border-color: lightgrey;
            }
            
            row {
                border-width: 1px;
                border-style: outset;
                border-color: lightgrey;
                min-height: 32px;
                min-width: 400px;
            }
            '''
            
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        style_context = self.get_style_context()
        style_context.add_provider_for_screen(
                self.get_screen(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        parent.connect("feed-update-start", self.on_feed_update_start)
        parent.connect("feed-update-complete", self.on_feed_update_complete)
        
        header = Gtk.HeaderBar()
        header.set_title('Slimbook ' + _('News'))
        header.set_show_close_button(True)

        self.btn_refresh = Gtk.Button.new_with_label(_("Refresh"))
        self.btn_refresh.connect("clicked", self.on_btn_refresh_clicked)
        header.pack_end(self.btn_refresh)

        self.set_titlebar(header)
        
        vbox = Gtk.VBox(spacing = 12)
        self.listbox = Gtk.ListBox()
        
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        
        self.add(vbox)
        vbox.pack_start(self.listbox,False,False,1)
        vbox.set_border_width(16)
        
        self.populate()
        
        self.show_all()
    
    def populate(self):
        feeds = check_news()
        
        for feed in feeds:
            
            grid = Gtk.Grid.new()
            grid.set_row_spacing(4)
            grid.set_column_spacing(8)
            
            lbl_title = Gtk.Label()
            lbl_title.set_markup("<b>{0}</b>".format(feed.title))
            lbl_title.set_halign(Gtk.Align.START)
            
            lbl_body = Gtk.Label(label = feed.body)
            lbl_body.set_halign(Gtk.Align.START)
            if (feed.link):
                btn_link = Gtk.LinkButton(uri = feed.link, label = feed.link)
                btn_link.set_halign(Gtk.Align.START)
                grid.attach(btn_link,1,2,1,1)
             
            theme = Gtk.IconTheme()
            pix = theme.load_icon(icon_name = feed.icon, size = 32, flags = Gtk.IconLookupFlags.FORCE_SYMBOLIC)
            
            img = Gtk.Image.new_from_pixbuf(pix)
            
            grid.attach(img,0,0,1,4)
            
            grid.attach(lbl_title,1,0,1,1)
            grid.attach(lbl_body,1,1,1,1)
            
            row = Gtk.ListBoxRow()
            row.add(grid)
            
            self.listbox.add(row)
            
        self.listbox.show_all()
        
    
    def on_btn_refresh_clicked(self, widget):
        self.parent.update_feed()

    def on_feed_update_start(self, *args):
        self.btn_refresh.set_sensitive(False)
        children = self.listbox.get_children()
        
        for child in children:
            self.listbox.remove(child)
        
    def on_feed_update_complete(self, *args):
        self.btn_refresh.set_sensitive(True)
        self.populate()

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

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    value = connection.call_sync(
        BUS_NAME,
        BUS_PATH,
        BUS_NAME,
        "ShowPreferences",
        None,
        None,
        Gio.DBusCallFlags.NONE,
        10000,
        None)
        
    
    
    
    """"
    try:
        init_indicator()

    except:
        bus = dbus.SessionBus()
        session = bus.get_object(BUS_NAME, BUS_PATH)
        show_preferences = session.get_dbus_method(
            'show_preferences', BUS_NAME)
        # Call the methods with their specific parameters
        show_preferences()
    """

def init_indicator():
    
    try:
        service = ServiceIndicator()
        GLib.MainLoop().run()
    except KeyboardInterrupt as ke:
        GLib.MainLoop().quit()
        logging.info("out of main loop")
        exit(0)

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
