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
import sni

import logging
import threading
import subprocess
import os
import sys

# force WM_CLASS for window manager icon matching
sys.argv[0] = "slimbook-indicator"
import shutil
import common
import webbrowser
import hashlib
import time
import signal
import fnmatch
import datetime
from dateutil import parser


gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Notify", "0.7")

from gi.repository import GObject
from gi.repository import Gtk, Gdk, Gio
from gi.repository import GLib
from gi.repository import Adw
from gi.repository import Notify

Adw.init()

Notify.init("Slimbook Client Notifications")
notification = Notify.Notification.new("", "")
notification.set_app_name("Slimbook Client Notifications")
notification.set_timeout(Notify.EXPIRES_DEFAULT)
notification.set_urgency(Notify.Urgency.NORMAL)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] (%(threadName)-10s) %(message)s",
)

zmq_context = zmq.Context()


def update_server_settings(settings):
    def _send():
        logging.info("Updating server settings...")
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 1000)  # wait for in-flight messages on close
        sock.setsockopt(zmq.SNDTIMEO, 2000)
        sock.setsockopt(zmq.RCVTIMEO, 2000)
        sock.connect("ipc://{0}".format(common.SLB_IPC_CTL_PATH))
        data = {"cmd": common.CMD_LOAD_SETTINGS, "settings": settings}
        try:
            sock.send_json(data)
            sock.recv()
            logging.info("update_server_settings: OK")
        except zmq.Again:
            logging.warning("update_server_settings: service not available")
        except Exception as e:
            logging.warning("update_server_settings: error: %s", e)
        sock.close()
        ctx.term()

    threading.Thread(target=_send, daemon=True).start()


class Feed:
    def __init__(self, entry):
        try:
            m = hashlib.md5()
            m.update(str(entry).encode())

            self.id = m.hexdigest()
            self.title = entry.title
            self.body = entry.description
            link = entry.get("link", "")
            self.link = link if link.startswith(("http://", "https://")) else None
            self.published = entry.get("published")
            self.tags = []
            self.icon = "dialog-information"

            self.cached = False
            self.old = False

            if self.published:
                now = datetime.datetime.now(datetime.timezone.utc)
                ptime = parser.parse(self.published)
                delta = now - ptime
                self.old = delta.days > 90
            else:
                self.old = True

            if entry.get("tags"):
                for tag in entry.tags:
                    term = tag.get("term")

                    if term:
                        self.tags.append(term)

                        if term == "firmware":
                            self.icon = "application-x-firmware"

        except Exception as e:
            print(e)


def load_cache_feeds():
    feeds = []

    try:
        cache_file = os.path.expanduser("~/.cache/slimbook-service/feeds.dat")
        f = open(cache_file, "r")
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
        os.makedirs(cache_path, exist_ok=True)

        f = open(cache_path + "feeds.dat", "w")
        for feed in feeds:
            f.write(feed.id + "\n")

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


class ServiceIndicator(GObject.Object):
    __gsignals__ = {
        "feed-update-start": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,)),
        "feed-update-complete": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,)),
    }

    def __init__(self):
        super().__init__()

        # set up zmq
        self.socket = zmq_context.socket(zmq.SUB)
        self.socket.connect("ipc://{0}".format(common.SLB_IPC_PATH))
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)

        GLib.idle_add(self.zmq_loop)

        # menu item sensitivity
        self._news_sensitive = True
        self._prefs_sensitive = True
        self._report_sensitive = True

        self.set_indicator()
        Notify.init("Slimbook")

        GLib.timeout_add_seconds(5, self.on_notifications_timeout)

        self.feed_updating = False

    def zmq_loop(self):
        while self.poller.poll(timeout=50):
            data = self.socket.recv_json()
            code = data.get("code")
            event = common.SLB_EVENT_DATA.get(code)
            # avoid crashing on unhandled event codes
            if event is None:
                continue

            self.message("Slimbook", event[0], event[1])

        return True

    def on_notifications_timeout(self):
        if self.notifications_enabled:
            if not check_time_feeds():
                self.update_feed()

        GLib.timeout_add_seconds(3600 * 6, self.on_notifications_timeout)

        return False

    def update_feed(self):
        logging.info("updating feed...")

        if self.feed_updating == False:
            self.emit("feed-update-start", False)
            self.feed_updating = True
            thread = threading.Thread(target=self.update_feed_worker)
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

        if self._news_sensitive:
            self.check_news()

    def check_news(self):
        news = []
        warn_user = False

        logging.info("checking news...")
        cached = load_cache_feeds()

        product = slimbook.info.product_name().lower().strip()
        sku = slimbook.info.product_sku().lower().strip()
        family = slimbook.info.get_family_name()
        ec_firmware = slimbook.info.ec_firmware_release()
        bios_version = slimbook.info.bios_version()
        logging.info("model:{0}".format(product))
        logging.info("sku:{0}".format(sku))
        logging.info("family:{0}".format(family))
        logging.info("ec:{0}".format(ec_firmware))
        logging.info("bios:{0}".format(bios_version))

        try:
            feed = feedparser.parse(
                os.path.expanduser("~/.cache/slimbook-service/sb-rss.xml")
            )
            now = datetime.datetime.now(datetime.timezone.utc)

            for entry in feed["entries"]:
                nw = Feed(entry)
                filters = 0
                match = False

                for tag in nw.tags:
                    if tag.startswith("family:"):
                        target = tag.split(":")[1]
                        filters = filters + 1
                        if fnmatch.fnmatch(family, target):
                            logging.info(
                                "feed match family filter:{0}={1}".format(
                                    family, target
                                )
                            )
                            match = True

                    if tag.startswith("model:"):
                        target = tag.split(":")[1]
                        filters = filters + 1

                        if fnmatch.fnmatch(product, target):
                            logging.info(
                                "feed match product filter:{0}={1}".format(
                                    product, target
                                )
                            )
                            match = True
                        elif fnmatch.fnmatch(sku, target):
                            logging.info(
                                "feed match sku filter:{0}={1}".format(sku, target)
                            )
                            match = True

                if filters > 0 and match == False:
                    logging.info("entry ignored by filter")
                    continue

                for cid in cached:
                    if cid == nw.id:
                        logging.info("id cached:{0}".format(nw.id))
                        nw.cached = True
                        break

                news.append(nw)

                body = nw.body

                if nw.link:
                    body = body + " " + nw.link

                if nw.cached == False and nw.old == False:
                    nt = Notify.Notification.new(nw.title, body, nw.icon)
                    nt.show()

                    warn_user = True

            store_cache_feeds(news)

        except Exception as e:
            logging.error(e)

        if warn_user:
            self.indicator.set_status(sni.STATUS_NEEDS_ATTENTION)
        else:
            if self.show:
                self.indicator.set_status(sni.STATUS_ACTIVE)
            else:
                self.indicator.set_status(sni.STATUS_PASSIVE)

        return news

    def set_indicator(self):
        logging.debug("Setting indicator...")
        self.active_icon = None
        self.attention_icon = None
        self.active = False

        self.notification = Notify.Notification.new("", "", None)
        self.read_preferences()
        manage_autostart(self.autostart)

        self.indicator = sni.StatusNotifierItem(
            "com.slimbook.service",
            self.active_icon,
            sni.CATEGORY_HARDWARE,
        )
        self.indicator.set_title("Slimbook Client Notifications")
        self.indicator.set_attention_icon(self.attention_icon)

        self.running = True
        self._refresh_menu()

        if self.show:
            self.indicator.set_status(sni.STATUS_ACTIVE)
        else:
            self.indicator.set_status(sni.STATUS_PASSIVE)

    def _refresh_menu(self):
        """Rebuild and push the tray menu to the SNI indicator."""
        self.indicator.set_menu(self._build_menu_items())

    def _build_menu_items(self):
        """Return a list of SNI menu item descriptors."""
        items = [
            {
                "label": _("Notifications"),
                "callback": self.on_news_item,
                "sensitive": self._news_sensitive,
            },
            {
                "label": _("System Information"),
                "callback": self.on_sysinfo_item,
            },
            {
                "label": _("Preferences"),
                "callback": self.on_preferences_item,
                "sensitive": self._prefs_sensitive,
            },
        ]

        if os.path.exists(common.CONTROL_PANEL_PATH):
            items.append({
                "label": _("Control Panel"),
                "callback": self.on_control_panel_item,
            })

        items.append({"type": "separator", "label": ""})

        items += [
            {
                "label": _("About"),
                "callback": self.on_about_item,
            },
            {
                "label": _("Generate Report"),
                "callback": self.on_report_item,
                "sensitive": self._report_sensitive,
            },
            {
                "label": _("Report a Bug…"),
                "callback": lambda: webbrowser.open(
                    "https://github.com/slimbook/slimbook_service/issues/new"
                ),
            },
        ]

        items.append({"type": "separator", "label": ""})

        items.append({
            "label": _("Exit"),
            "callback": self.on_quit_item,
        })

        return items

    def message(self, title, message, icon="dialog-information"):
        notification.update(title, message, icon)
        notification.show()

    def read_preferences(self):
        configuration = Configuration()
        self.first_time = configuration.get("first-time")
        self.autostart = configuration.get("autostart")
        self.version = configuration.get("version")
        self.theme = configuration.get("theme")
        self.active_icon = common.STATUS_ICON[configuration.get("theme")]
        self.attention_icon = common.STATUS_ICON[self.theme + "-attention"]
        self.show = configuration.get("show")
        self.notifications_enabled = configuration.get("notifications")

        # push settings to server
        settings = {}

        for key in [common.OPT_TRACKPAD_LOCK, common.OPT_POWER_PROFILE, common.OPT_AC_NOTIFICATIONS]:
            value = configuration.get(key)
            if value is not None:
                settings[key] = value

        update_server_settings(settings)

    def on_preferences_item(self, *args):
        self.show_preferences()

    def on_control_panel_item(self, *args):
        subprocess.Popen([common.CONTROL_PANEL_PATH])

    def on_sysinfo_item(self, *args):
        logging.debug("system info")
        info = common.get_system_info()
        sysinfo_dialog = SystemInfoDialog(info)
        sysinfo_dialog.present()

    def on_news_item(self, *args):
        logging.debug("news")
        self._news_sensitive = False
        self._refresh_menu()
        news_dialog = NotificationsDialog(self)
        news_dialog.connect("close-request", self._on_news_close_request)
        news_dialog.present()

    def on_quit_item(self, *args):
        Notify.uninit()
        logging.debug("Exit")
        if _main_loop:
            _main_loop.quit()

    def on_about_item(self, *args):
        dialog = Adw.AboutDialog(
            application_name=common.APPNAME,
            application_icon=common.ICON,
            version=common.VERSION,
            developer_name="Slimbook",
            copyright="Copyright © 2024 Slimbook",
            comments=_("Slimbook Service"),
            license_type=Gtk.License.GPL_3_0,
            website="http://www.slimbook.es",
            issue_url="https://github.com/slimbook/slimbook_service/issues/new",
            developers=["Slimbook <dev@slimbook.es>", "Antonio Masiá <ajmasia.dev@ysnp.link>"],
            documenters=["Slimbook <dev@slimbook.es>"],
            translator_credits=_("translator-credits"),
        )
        dialog.present(None)

    def on_report_item(self, *args):
        self.show_report()

    # dialog callbacks

    def _on_news_close_request(self, window):
        self._news_sensitive = True
        self._refresh_menu()
        if self.show:
            self.indicator.set_status(sni.STATUS_ACTIVE)
        else:
            self.indicator.set_status(sni.STATUS_PASSIVE)
        return False  # allow close

    def on_preferences_close(self, dialog, changes):
        self._prefs_sensitive = True
        self._refresh_menu()
        self.read_preferences()
        self.indicator.set_attention_icon(self.attention_icon)
        self.indicator.set_icon(self.active_icon)

    def show_preferences(self):
        self._prefs_sensitive = False
        self._refresh_menu()
        preferences_dialog = PreferencesDialog()
        preferences_dialog.connect("preferences-close", self.on_preferences_close)
        preferences_dialog.present(None)

    def show_report(self):
        self._report_sensitive = False
        self._refresh_menu()
        report_dialog = ReportDialog()
        report_dialog.connect("close-request", self._on_report_close_request)
        report_dialog.present()

    def _on_report_close_request(self, window):
        self._report_sensitive = True
        self._refresh_menu()
        return False


# ---------------------------------------------------------------------------
# ReportDialog
# ---------------------------------------------------------------------------

class ReportDialog(Adw.Window):
    def __init__(self):
        super().__init__()
        self.set_default_size(500, 520)
        self.set_modal(True)
        self.set_title(_("Generate Report"))

        self.path = ""

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)

        self.stack = Gtk.Stack()

        # Report view
        status_report = Adw.StatusPage(
            icon_name="document-send-symbolic",
            title=_("Generate Report"),
            description=_(
                "Creates a compressed archive with hardware and software information. "
                "The full report also includes sensitive data such as MAC address and board serial number"
            ),
        )
        self.normal_report_btn = Gtk.Button.new_with_label(_("Report"))
        self.normal_report_btn.add_css_class("pill")
        self.normal_report_btn.connect("clicked", self.on_report_button)
        self.full_report_btn = Gtk.Button.new_with_label(_("Full Report"))
        self.full_report_btn.add_css_class("pill")
        self.full_report_btn.connect("clicked", self.on_full_report_button)
        btn_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        btn_box.append(self.normal_report_btn)
        btn_box.append(self.full_report_btn)
        status_report.set_child(btn_box)

        # Generating view
        status_generating = Adw.StatusPage(title=_("Generating…"))
        spinner = Adw.Spinner()
        spinner.set_size_request(32, 32)
        status_generating.set_child(spinner)

        # Success view
        self.status_success = Adw.StatusPage(icon_name="object-select-symbolic")
        self.open_btn = Gtk.Button.new_with_label(_("Open Folder"))
        self.open_btn.add_css_class("suggested-action")
        self.open_btn.add_css_class("pill")
        self.open_btn.set_halign(Gtk.Align.CENTER)
        self.open_btn.connect("clicked", self.on_open_button)
        self.status_success.set_child(self.open_btn)

        # Error view
        self.status_error = Adw.StatusPage(icon_name="dialog-error-symbolic")
        close_btn_err = Gtk.Button.new_with_label(_("Close"))
        close_btn_err.set_halign(Gtk.Align.CENTER)
        close_btn_err.connect("clicked", self.on_close_button)
        self.status_error.set_child(close_btn_err)

        self.stack.add_named(status_report, name="report")
        self.stack.add_named(status_generating, name="generating")
        self.stack.add_named(self.status_success, name="success")
        self.stack.add_named(self.status_error, name="error")

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(self.stack)
        self.set_content(toolbar_view)

    def prog_bar_proc(self, args):
        done, err_msg, path = args[0], args[1], args[2]
        if not done:
            return
        if err_msg:
            self.status_error.set_title(_("Error"))
            self.status_error.set_description(
                _("The report could not be generated:\n") + err_msg
            )
            self.stack.set_visible_child_name("error")
        else:
            self.path = path
            self.status_success.set_title(_("Report Generated"))
            self.status_success.set_description(_("Saved at ") + path)
            self.stack.set_visible_child_name("success")

    def on_report_button_common(self, widget, report_type):
        self.stack.set_visible_child_name("generating")
        self.disable_buttons()
        ReportThread(self.prog_bar_proc, report_type).start()

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


# ---------------------------------------------------------------------------
# ReportThread
# ---------------------------------------------------------------------------

class ReportThread(threading.Thread):
    def __init__(self, cb, report_type):
        threading.Thread.__init__(self)
        self.callback = cb
        self.report_type = report_type

    def run(self):
        common.report_proc(self, GLib.idle_add, self.callback, self.report_type)


# ---------------------------------------------------------------------------
# PreferencesDialog
# ---------------------------------------------------------------------------

class PreferencesDialog(Adw.PreferencesDialog):
    __gsignals__ = {
        "preferences-close": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_BOOLEAN,))
    }

    _PREFS = [
        ("switch0", lambda: _("Show Indicator")),
        ("switch1", lambda: _("Autostart")),
        ("switch2", lambda: _("Light-Mode Icon")),
        ("switch3", lambda: _("Check Notifications")),
        ("switch4", lambda: _("Trackpad Lock")),
        ("switch5", lambda: _("Set Power Profile")),
        ("switch6", lambda: _("AC Notifications")),
    ]

    def __init__(self):
        super().__init__()
        self.set_wmclass("slimbook-indicator", "slimbook-indicator")
        self.set_title(_("Slimbook Preferences"))

        page = Adw.PreferencesPage()
        self.add(page)

        group = Adw.PreferencesGroup()
        page.add(group)

        for attr, label_fn in self._PREFS:
            row = Adw.SwitchRow(title=label_fn())
            group.add(row)
            setattr(self, attr, row)

        self.btn_save = Gtk.Button.new_with_label(_("Save"))
        self.btn_save.add_css_class("suggested-action")
        self.btn_save.add_css_class("pill")
        self.btn_save.set_halign(Gtk.Align.CENTER)
        self.btn_save.set_margin_top(12)
        self.btn_save.set_sensitive(False)
        self.btn_save.connect("clicked", self._on_btn_save_clicked)
        group.add(self.btn_save)

        self._load_preferences()

        for attr, __ in self._PREFS:
            getattr(self, attr).connect("notify::active", self._on_switch_changed)

    def _on_switch_changed(self, row, _param):
        self._changes = True
        self.btn_save.set_sensitive(True)

    def _on_btn_save_clicked(self, _btn):
        self._save_preferences()
        self._changes = False
        self.btn_save.set_sensitive(False)

    def _on_dialog_closed(self, *args):
        self.emit("preferences-close", self._changes)

    def _load_preferences(self):
        configuration = Configuration()
        first_time = configuration.get("first-time")
        version = configuration.get("version")
        if first_time or version != common.VERSION:
            configuration.set_defaults()
            configuration.read()

        self.switch0.set_active(configuration.get("show") == True)
        self.switch1.set_active(os.path.exists(common.FILE_AUTO_START))
        self.switch2.set_active(configuration.get("theme") == "light")
        self.switch3.set_active(configuration.get("notifications") == True)
        self.switch4.set_active(configuration.get("trackpad-lock") == True)
        self.switch5.set_active(configuration.get("power-profile") == True)
        self.switch6.set_active(configuration.get("ac-notifications") == True)

    def _save_preferences(self):
        configuration = Configuration()
        configuration.set("first-time", False)
        configuration.set("version", common.VERSION)
        configuration.set("show", self.switch0.get_active())

        manage_autostart(self.switch1.get_active())
        if self.switch2.get_active():
            configuration.set("theme", "light")
        else:
            configuration.set("theme", "dark")

        configuration.set("notifications", self.switch3.get_active())
        configuration.set("trackpad-lock", self.switch4.get_active())
        configuration.set("power-profile", self.switch5.get_active())
        configuration.set("ac-notifications", self.switch6.get_active())
        configuration.save()

        settings = {}
        settings[common.OPT_TRACKPAD_LOCK] = self.switch4.get_active()
        settings[common.OPT_POWER_PROFILE] = self.switch5.get_active()
        settings[common.OPT_AC_NOTIFICATIONS] = self.switch6.get_active()
        update_server_settings(settings)


# ---------------------------------------------------------------------------
# SystemInfoDialog
# ---------------------------------------------------------------------------

class SystemInfoDialog(Adw.Window):
    def __init__(self, info):
        super().__init__()
        self.set_title(_("Slimbook System Information"))
        self.set_default_size(700, 640)
        self.set_modal(True)
        self.info = info

        btn_copy = Gtk.Button.new_from_icon_name("edit-copy")
        btn_copy.set_tooltip_text(_("Copy to Clipboard"))
        btn_copy.connect("clicked", self._btn_copy_clicked)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        header.pack_end(btn_copy)

        group = Adw.PreferencesGroup()
        for k in info:
            key, value = k[0], k[1].strip()
            row = Adw.ActionRow(title=key)
            val_label = Gtk.Label(label=value)
            val_label.add_css_class("dimmed")
            val_label.set_selectable(True)
            val_label.set_wrap(True)
            val_label.set_hexpand(True)
            val_label.set_halign(Gtk.Align.END)
            val_label.set_valign(Gtk.Align.CENTER)
            val_label.set_use_markup(False)
            row.add_suffix(val_label)
            group.add(row)

        page = Adw.PreferencesPage()
        page.add(group)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(page)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(self._toast_overlay)
        self.set_content(toolbar_view)

    def _btn_copy_clicked(self, button):
        txt = "".join("{0}:\t{1}\n".format(k[0], k[1]) for k in self.info)
        button.get_clipboard().set(txt)
        self._toast_overlay.add_toast(Adw.Toast(title=_("Copied to clipboard")))


# ---------------------------------------------------------------------------
# NotificationsDialog
# ---------------------------------------------------------------------------

class NotificationsDialog(Adw.Window):
    def __init__(self, parent):
        super().__init__()
        self.set_modal(True)
        self.set_default_size(500, 600)
        self.set_title(_("Slimbook Notifications"))
        self.parent = parent

        parent.connect("feed-update-start", self.on_feed_update_start)
        parent.connect("feed-update-complete", self.on_feed_update_complete)

        self.btn_refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.btn_refresh.set_tooltip_text(_("Refresh"))
        self.btn_refresh.connect("clicked", self.on_btn_refresh_clicked)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        header.pack_start(self.btn_refresh)

        self.toolbar_view = Adw.ToolbarView()
        self.toolbar_view.add_top_bar(header)
        self.set_content(self.toolbar_view)

        self._populate()

    def _make_feeds_page(self, feeds):
        group = Adw.PreferencesGroup()

        for feed in feeds:
            row = Adw.ActionRow(title=feed.title, subtitle=feed.body)
            row.set_use_markup(False)
            row.set_subtitle_lines(3)

            icon = Gtk.Image.new_from_icon_name(feed.icon)
            icon.set_pixel_size(32)
            row.add_prefix(icon)

            if feed.link:
                row.set_activatable(True)
                row.connect(
                    "activated",
                    lambda _row, url=feed.link: webbrowser.open(url),
                )
                row.set_tooltip_text(feed.link)
                suffix = Gtk.Image.new_from_icon_name("adw-external-link-symbolic")
                suffix.set_valign(Gtk.Align.CENTER)
                row.add_suffix(suffix)

            group.add(row)

        page = Adw.PreferencesPage()
        page.add(group)
        return page

    def _make_status_page(self, icon_name, title, with_spinner=False):
        status = Adw.StatusPage(icon_name="" if with_spinner else icon_name, title=title)
        if with_spinner:
            spinner = Adw.Spinner()
            spinner.set_size_request(32, 32)
            status.set_child(spinner)
        return status

    def _populate(self):
        feeds = self.parent.check_news()
        if feeds:
            self.toolbar_view.set_content(self._make_feeds_page(feeds))
        else:
            self.toolbar_view.set_content(
                self._make_status_page("face-plain-symbolic", _("Nothing to Show"))
            )

    def on_btn_refresh_clicked(self, widget):
        self.parent.update_feed()
        self._show_feed_update()

    def on_feed_update_start(self, *args):
        self._show_feed_update()

    def _show_feed_update(self):
        self.btn_refresh.set_sensitive(False)
        self.toolbar_view.set_content(
            self._make_status_page(
                "emblem-synchronizing-symbolic", _("Fetching…"), with_spinner=True
            )
        )

    def on_feed_update_complete(self, *args):
        self.btn_refresh.set_sensitive(True)
        self._populate()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def manage_autostart(create):
    if not os.path.exists(common.AUTOSTART_DIR):
        os.makedirs(common.AUTOSTART_DIR)
    if create:
        if not os.path.exists(common.FILE_AUTO_START):
            shutil.copyfile(common.FILE_AUTO_START_ORIG, common.FILE_AUTO_START)
    else:
        if os.path.exists(common.FILE_AUTO_START):
            os.remove(common.FILE_AUTO_START)


# ---------------------------------------------------------------------------
# Single-instance / main-loop management
# ---------------------------------------------------------------------------

PID_FILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "slimbook-service-indicator.pid"
)

_indicator_instance = None
_main_loop = None


def _on_sigusr1(*args):
    if _indicator_instance:
        GLib.idle_add(_indicator_instance.show_preferences)


def is_running():
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def send_preferences_signal():
    try:
        with open(PID_FILE, "r") as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGUSR1)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def init_indicator():
    global _indicator_instance, _main_loop
    try:
        _indicator_instance = ServiceIndicator()

        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        signal.signal(signal.SIGUSR1, _on_sigusr1)
        _main_loop = GLib.MainLoop()
        _main_loop.run()
    except KeyboardInterrupt:
        logging.info("out of main loop")
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        exit(0)


def main():
    if "--preferences" in sys.argv or "-p" in sys.argv:
        if send_preferences_signal():
            return
    elif is_running():
        return
    init_indicator()


if __name__ == "__main__":
    main()
