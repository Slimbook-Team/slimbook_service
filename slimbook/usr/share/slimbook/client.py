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

import zmq
import feedparser
import gi

import logging
import threading
import subprocess
import os
import sys
import shutil
import common
import webbrowser
import hashlib
import time
import signal
import fnmatch
from optparse import OptionParser


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
from gi.repository import GLib

BUS_NAME = 'es.slimbook.ServiceIndicator'
BUS_PATH = '/es/slimbook/ServiceIndicator'

Notify.init("Slimbok Client Notifications")
notification = Notify.Notification.new('', '' )
notification.set_app_name("Slimbok Client Notifications")
notification.set_timeout(Notify.EXPIRES_DEFAULT)
notification.set_urgency(Notify.Urgency.NORMAL)

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
            self.published = entry.get("published")
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
        return (now - mtime) < (3600)
    else:
        return False

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
        
        GLib.timeout_add_seconds(5,self.on_notifications_timeout)
        
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
            code = data.get("code")
            event = common.SLB_EVENT_DATA.get(code)
            # avoid crashing on unhandled event codes
            if (event == None):
                continue
            
            self.message("Slimbook",event[0],event[1])
        
        return True
    
    def on_notifications_timeout(self):
        if (self.notifications_enabled):
            if (not check_time_feeds()):
                self.update_feed()
        
        GLib.timeout_add_seconds(3600 * 6,self.on_notifications_timeout)
        
        return False
        
    def update_feed(self):
        logging.info("updating feed...")
        
        if self.feed_updating == False:
            self.emit('feed-update-start', False)
            self.feed_updating = True
            thread = threading.Thread(target = self.update_feed_worker)
            thread.daemon = True
            thread.start()
    
    def update_feed_worker(self):
        try:
            common.download_feed()
            GLib.idle_add(self.on_feed_update)
        except:
            logging.warning("failed to get rss feed (no connection?)")
    
    def on_feed_update(self):
        logging.info("feed has been updated")
        self.feed_updating = False
        self.emit("feed-update-complete", False)
        
        if (self.menu_news.get_sensitive()):
            self.check_news()
        
    def check_news(self):
    
        news = []
        warn_user = False
        
        logging.info("checking news...")
        cached = load_cache_feeds()
        
        product = slimbook.info.product_name().lower().strip()
        sku = slimbook.info.product_sku().lower().strip()
        family = slimbook.info.get_family_name()
        logging.info("model:{0}".format(product))
        logging.info("sku:{0}".format(sku))
        logging.info("family:{0}".format(family))
        
        try:
            feed = feedparser.parse(os.path.expanduser("~/.cache/slimbook-service/sb-rss.xml"))
        
            for entry in feed["entries"]:
                nw = Feed(entry)
                
                filters = 0
                match = False
                
                for tag in nw.tags:
                    if (tag.startswith("family:")):
                        target=tag.split(":")[1]
                        filters = filters + 1
                        if (fnmatch.fnmatch(family,target)):
                            logging.info("feed match family filter:{0}={1}".format(family,target))
                            match = True
                    
                    if (tag.startswith("model:")):
                        target=tag.split(":")[1]
                        filters = filters + 1
                        
                        if (fnmatch.fnmatch(product,target)):
                            logging.info("feed match product filter:{0}={1}".format(product,target))
                            match = True
                        elif (fnmatch.fnmatch(sku,target)):
                            logging.info("feed match sku filter:{0}={1}".format(sku,target))
                            match = True
                        
                if (filters > 0 and match == False):
                    logging.info("entry ignored by filter")
                    continue
                    
                for cid in cached:
                    if cid == nw.id:
                        logging.info("id cached:{0}".format(nw.id))
                        nw.cached = True
                        break
                        
                news.append(nw)
                
                body = nw.body
                
                if (nw.link):
                    body = body + " " + nw.link
                
                if (nw.cached == False):
                    nt = Notify.Notification.new(nw.title, body, nw.icon)
                    nt.show()
                    
                    warn_user = True
            
            store_cache_feeds(news)
            
                
        except Exception as e:
            logging.error(e)
        
        
        if (warn_user):
            self.indicator.set_status(appindicator.IndicatorStatus.ATTENTION)
        else:
            self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE) if self.show else self.indicator.set_status(
            appindicator.IndicatorStatus.PASSIVE)
            
        return news
    
    def set_indicator(self):

        logging.debug("Setting indicator...")
        self.active_icon = None
        self.attention_icon = None
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

        self.indicator.set_attention_icon_full(self.attention_icon,"")
        
        self.running = True
        
        self.menu = self.get_menu()
        self.indicator.set_menu(self.menu)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE) if self.show else self.indicator.set_status(
            appindicator.IndicatorStatus.PASSIVE)

    def message(self, title, message, icon = "dialog-information"):
        notification.update(title, message, icon)
        notification.show()

    def read_preferences(self):
        configuration = Configuration()
        self.first_time = configuration.get('first-time')
        self.autostart = configuration.get('autostart')
        self.version = configuration.get('version')
        self.theme = configuration.get('theme')
        self.active_icon = os.path.abspath(
            common.STATUS_ICON[configuration.get('theme')])
        self.attention_icon = common.STATUS_ICON[self.theme+"-attention"]
        self.show = configuration.get('show')
        self.notifications_enabled = configuration.get('notifications')
        

    def get_menu(self):
        """Create and populate the menu."""
        menu = Gtk.Menu()

        separator1 = Gtk.SeparatorMenuItem()
        separator1.show()
        menu.append(separator1)

        self.menu_news = Gtk.MenuItem.new_with_label(_('Notifications'))
        self.menu_news.connect('activate', self.on_news_item)
        self.menu_news.show()
        menu.append(self.menu_news)
        
        menu_sysinfo = Gtk.MenuItem.new_with_label(_('System information'))
        menu_sysinfo.connect('activate', self.on_sysinfo_item)
        menu_sysinfo.show()
        menu.append(menu_sysinfo)
        
        self.menu_preferences = Gtk.MenuItem.new_with_label(_('Preferences'))
        self.menu_preferences.connect('activate', self.on_preferences_item)
        self.menu_preferences.show()
        menu.append(self.menu_preferences)
        
        about_item = Gtk.MenuItem.new_with_label(_('About'))
        about_item.connect('activate', self.on_about_item)
        about_item.show()
        separator = Gtk.SeparatorMenuItem()
        separator.show()
        menu.append(separator)
        menu.append(about_item)

        self.report = Gtk.MenuItem.new_with_label(_('Generate report'))
        self.report.connect('activate', self.on_report_item)
        self.report.show()
        menu.append(self.report)

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
        news_dialog = NotificationsDialog(self)
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

    def on_report_item(self, widget, data=None):
        self.show_report()
        widget.set_sensitive(True)

    # Interface and Method

    def on_news_delete_event(self, window, event):
        self.menu_news.set_sensitive(True)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE) if self.show else self.indicator.set_status(
            appindicator.IndicatorStatus.PASSIVE)

    def on_preferences_close(self, *args):
        self.menu_preferences.set_sensitive(True)
        self.read_preferences()
        
        self.indicator.set_attention_icon_full(self.attention_icon,"")
        self.indicator.set_icon_full(self.active_icon,"")
        
    def show_preferences(self):
        self.menu_preferences.set_sensitive(False)
        preferences_dialog = PreferencesDialog()
        preferences_dialog.connect("preferences-close",self.on_preferences_close)

    def show_report(self):
        self.report.set_sensitive(False)
        report_dialog = ReportDialog()

class ReportDialog(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self)
        self.set_default_size(600, 100)
        self.set_modal(True)

        self.path = ""
        self.has_ended = False

        self.connect('delete-event',self.on_report_delete_event)
                
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_icon(GdkPixbuf.Pixbuf.new_from_file_at_scale(
            common.ICON, 64, 64, True))

        header = Gtk.HeaderBar()
        header.set_title(_('Generate report'))
        header.set_show_close_button(True)

        self.set_titlebar(header)

        self.stack = Gtk.Stack()

        vboxrv = Gtk.VBox()
        vboxmv = Gtk.VBox()
        vboxev = Gtk.VBox()

        # Report View

        vboxrv.set_margin_start(20)
        vboxrv.set_margin_end(20)
        vboxrv.set_margin_top(10)
        vboxrv.set_margin_bottom(10)

        hboxrv = Gtk.HBox()
        hboxrv.set_margin_start(5)
        hboxrv.set_margin_end(5)

        report_desc = Gtk.Label.new("This is a report of several hardware and software stats.\nFull report generates a report with sensitive information,\nbeware of sharing it online!")

        vboxrv.pack_start(report_desc, True, True, 4)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_text("")
        self.progress_bar.set_show_text(True)

        vboxrv.pack_start(self.progress_bar, True, True, 4)

        self.normal_report_btn = Gtk.Button.new_with_label(_("Report"))
        self.normal_report_btn.connect("clicked",self.on_report_button)

        self.full_report_btn = Gtk.Button.new_with_label(_("Full report"))
        self.full_report_btn.connect("clicked",self.on_full_report_button)

        hboxrv.pack_start(self.normal_report_btn, True, True, 4)
        hboxrv.pack_start(self.full_report_btn, True, True, 4)
        
        vboxrv.pack_start(hboxrv, True, True, 4)

        # Message View

        vboxmv.set_margin_start(20)
        vboxmv.set_margin_end(20)
        vboxmv.set_margin_top(10)
        vboxmv.set_margin_bottom(10)

        hboxmv = Gtk.HBox()
        hboxmv.set_margin_start(10)
        hboxmv.set_margin_end(10)
        hboxmv.set_margin_top(15)
        hboxmv.set_margin_bottom(15)

        self.path_label = Gtk.Label.new(self.path)
        vboxmv.pack_start(self.path_label, True, True, 4)

        self.open_btn = Gtk.Button.new_with_label(_('Open'))
        self.open_btn.connect("clicked", self.on_open_button)

        self.close_btn = Gtk.Button.new_with_label(_('Close'))
        self.close_btn.connect("clicked", self.on_close_button)

        hboxmv.pack_start(self.open_btn, True, True, 4)
        hboxmv.pack_start(self.close_btn, True, True, 4)

        vboxmv.pack_start(hboxmv, True, True, 4)

        # Error view

        vboxev.set_margin_start(20)
        vboxev.set_margin_end(20)
        vboxev.set_margin_top(10)
        vboxev.set_margin_bottom(10)

        hboxev = Gtk.HBox()
        hboxev.set_margin_start(10)
        hboxev.set_margin_end(10)
        hboxev.set_margin_top(15)
        hboxev.set_margin_bottom(15)

        self.err_code = ""

        self.err_code_label = Gtk.Label.new(self.err_code)

        vboxev.pack_start(self.err_code_label, True, True, 4)

        self.close_btn_err = Gtk.Button.new_with_label(_('Close'))
        self.close_btn_err.connect("clicked", self.on_close_button)

        hboxev.pack_start(self.close_btn_err, True, True, 4)

        vboxev.pack_start(hboxev, True, True, 4)

        self.stack.add_named(vboxrv, name = "Report view")

        self.stack.add_named(vboxmv, name = "Message view")

        self.stack.add_named(vboxev, name = "Error view")

        self.add(self.stack)

        self.show_all()

    def prog_bar_proc(self, args):
        if args[0] == True:
            self.path_label.set_label("Succesful! Dumped at " + self.path)
            self.resize(200, 100)
            self.stack.set_visible_child_name("Message view")
            self.progress_bar.set_fraction(1.0)
        else:
            self.progress_bar.pulse()
        
        if args[1] != "":
            self.err_code_label.set_label("Error! Report wasn't able to be generated\nError : " + self.err_code)
            self.stack.set_visible_child_name("Error view")
            self.resize(200, 100)
            self.err_code = args[1]

        if args[2] != "":
            self.path = args[2]


    def on_report_button_common(self, widget, str):
        self.bar_thread = ReportThread(self.prog_bar_proc, str)
        self.bar_thread.start()
        self.disable_buttons()

    def on_report_button(self, widget):
        self.on_report_button_common(widget, "report")

    def on_full_report_button(self, widget):
        self.on_report_button_common(widget, "report-full")

    def disable_buttons(self):
        self.normal_report_btn.set_sensitive(False)
        self.full_report_btn.set_sensitive(False)  

    def on_close_button(self, widget):
        self.close()
    
    def on_open_button(self, widget):
        subprocess.Popen(["xdg-open", os.path.dirname(self.path)])


    def on_report_delete_event(self, window, event):
        self.set_sensitive(False)

class ReportThread(threading.Thread):
    def __init__(self, cb, report_type):
        threading.Thread.__init__(self)
        self.callback = cb
        self.report_type = report_type

    def run(self):
        common.report_proc(self, GLib.idle_add, self.callback, self.report_type)


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
        self.btn_save.connect("clicked",self.on_btn_save_clicked)
        header.pack_end(self.btn_save)
        self.set_titlebar(header)

        vbox0 = Gtk.VBox(spacing=5)
        vbox0.set_border_width(20)
        self.add(vbox0)
        table1 = Gtk.Table(n_rows = 10, n_columns = 2, homogeneous = False)
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
        label2 = Gtk.Label(label=_('Light-mode Icon') + ':')
        label2.set_halign(Gtk.Align.CENTER)
        table1.attach(label2, 0, 1, 8, 9, xpadding=15, ypadding=15)
        self.switch2 = Gtk.Switch()
        table1.attach(self.switch2, 1, 2, 8, 9, xpadding=15, ypadding=15,
                      xoptions=Gtk.AttachOptions.SHRINK)
        
        label3 = Gtk.Label(label=_('Check Notifications') + ':')
        label3.set_halign(Gtk.Align.CENTER)
        table1.attach(label3, 0, 1, 9, 10, xpadding=15, ypadding=15)
        self.switch3 = Gtk.Switch()
        table1.attach(self.switch3, 1, 2, 9, 10, xpadding=15, ypadding=15,
                      xoptions=Gtk.AttachOptions.SHRINK)
        
        self.load_preferences()
        
        self.changes = False
        self.switch0.connect('state-set',self.on_switch_state_set)
        self.switch1.connect('state-set',self.on_switch_state_set)
        self.switch2.connect('state-set',self.on_switch_state_set)
        self.switch3.connect('state-set',self.on_switch_state_set)
        
        self.show_all()

    def on_switch_state_set(self, switch, state):
        self.btn_save.set_sensitive(True)
        self.changes = True
    
    def on_delete_event(self, window, event):
        self.emit('preferences-close', self.changes)
        return False
    
    def on_btn_save_clicked(self, widget):
        self.save_preferences()
        self.btn_save.set_sensitive(False)
        
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
        self.switch3.set_active(configuration.get('notifications') == True)

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
        
        configuration.set('notifications', self.switch3.get_active())
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
                min-width: 600px;
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
            label_key = Gtk.Label(label=key)
            #label_key.set_markup("<b>{0}</b>".format(key))
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

class NotificationsDialog(Gtk.Window):

    def __init__(self, parent):
        Gtk.Window.__init__(self)
        self.set_modal(True)
        self.parent = parent
        self.set_default_size(500,600)
        
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
        header.set_title('Slimbook ' + _('Notifications'))
        header.set_show_close_button(True)

        self.btn_refresh = Gtk.Button.new_with_label(_("Refresh"))
        self.btn_refresh.connect("clicked", self.on_btn_refresh_clicked)
        header.pack_end(self.btn_refresh)

        self.set_titlebar(header)
        
        vbox = Gtk.VBox(spacing = 12)
        sw = Gtk.ScrolledWindow()
        self.listbox = Gtk.ListBox()
        
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        
        self.add(vbox)
        sw.add(self.listbox)
        vbox.pack_start(sw,True,True,1)
        vbox.set_border_width(16)
        
        self.populate()
        
        self.show_all()
    
    def populate(self):
        #feeds = check_news()
        feeds = self.parent.check_news()
        
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
        
        if (len(feeds) == 0):
            theme = Gtk.IconTheme()
            
            pix = theme.load_icon(icon_name = "face-plain-symbolic", size = 32, flags = Gtk.IconLookupFlags.FORCE_SYMBOLIC)
            
            img = Gtk.Image.new_from_pixbuf(pix)
            lbl = Gtk.Label(label = _("Nothing to show"))
            
            grid = Gtk.Grid.new()
            grid.set_row_spacing(4)
            grid.set_column_spacing(8)
            grid.attach(img,0,0,1,4)
            grid.attach(lbl,1,1,1,1)
                
            row = Gtk.ListBoxRow()
            row.add(grid)
            
            self.listbox.add(row)
        
        self.listbox.show_all()
        
    
    def on_btn_refresh_clicked(self, widget):
        self.parent.update_feed()
        self.show_feed_update()
        

    def on_feed_update_start(self, *args):
        self.show_feed_update()
            
    
    def show_feed_update(self):
        self.btn_refresh.set_sensitive(False)
        children = self.listbox.get_children()
        for child in children:
            self.listbox.remove(child)
        
        theme = Gtk.IconTheme()

        pix = theme.load_icon(icon_name = "emblem-synchronizing-symbolic", size = 32, flags = Gtk.IconLookupFlags.FORCE_SYMBOLIC)
        
        img = Gtk.Image.new_from_pixbuf(pix)
        lbl = Gtk.Label(label = _("Fetching..."))
        
        grid = Gtk.Grid.new()
        grid.set_row_spacing(4)
        grid.set_column_spacing(8)
        grid.attach(img,0,0,1,4)
        grid.attach(lbl,1,1,1,1)
            
        row = Gtk.ListBoxRow()
        row.add(grid)
            
        self.listbox.add(row)
        self.listbox.show_all()
        
    def on_feed_update_complete(self, *args):
        self.btn_refresh.set_sensitive(True)
        children = self.listbox.get_children()
        
        for child in children:
            self.listbox.remove(child)
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
            try:
                preferences()
            except Exception as e:
                logging.warning("slimbook-service dbus not available. Not running?")
                init_indicator()
                
        exit(0)
    else:
        logging.debug("Try Indicator init")
        init_indicator()


if __name__ == "__main__":
    main()
