#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Slimbook Service
# Copyright (C) 2026 Slimbook
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

# StatusNotifierItem + com.canonical.dbusmenu implementation via python-dbus.
# Replaces AyatanaAppIndicator3 so the indicator can run as a pure GTK4 process.

import logging
import dbus
import dbus.service
import dbus.mainloop.glib

# Integrate D-Bus GLib main loop with the GLib main loop already used by the app.
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

# ---------------------------------------------------------------------------
# Status constants (mirror AppIndicator's IndicatorStatus enum)
# ---------------------------------------------------------------------------
STATUS_ACTIVE = "Active"
STATUS_PASSIVE = "Passive"
STATUS_NEEDS_ATTENTION = "NeedsAttention"

CATEGORY_HARDWARE = "Hardware"


# ---------------------------------------------------------------------------
# DBusMenu  (com.canonical.dbusmenu)
# ---------------------------------------------------------------------------
_DBUSMENU_IFACE = "com.canonical.dbusmenu"


class _DbusMenu(dbus.service.Object):
    """Minimal DBusMenu implementation.

    Items are plain dicts::

        {"label": str, "callback": callable|None,
         "sensitive": bool, "type": "standard"|"separator",
         "id": int}   # assigned internally
    """

    def __init__(self, bus, path):
        dbus.service.Object.__init__(self, bus, path)
        self._items = []
        self._revision = 0

    def set_items(self, items):
        """Replace menu contents. items: list of dicts (label/callback/sensitive/type)."""
        self._items = []
        for idx, item in enumerate(items):
            entry = dict(item)
            entry["id"] = idx + 1          # id=0 is reserved for root
            entry.setdefault("sensitive", True)
            entry.setdefault("type", "standard")
            entry.setdefault("callback", None)
            self._items.append(entry)
        self._revision += 1
        self.LayoutUpdated(self._revision, 0)

    def _item_props(self, item):
        props = dbus.Dictionary(signature="sv")
        props["label"] = dbus.String(item.get("label", ""))
        props["enabled"] = dbus.Boolean(item.get("sensitive", True))
        props["visible"] = dbus.Boolean(True)
        props["type"] = dbus.String(item.get("type", "standard"))
        return props

    def _build_layout(self, parent_id, recursion_depth, property_names):
        """Return (id, props, children) tuple for the root."""
        root_props = dbus.Dictionary(signature="sv")
        children = dbus.Array(signature="v")
        for item in self._items:
            child_props = self._item_props(item)
            child = dbus.Struct(
                [dbus.Int32(item["id"]), child_props, dbus.Array([], signature="v")],
                signature=None,
            )
            children.append(dbus.Struct(child, signature=None))
        return dbus.Struct(
            [dbus.Int32(0), root_props, children],
            signature=None,
        )

    # --- DBus methods ---

    @dbus.service.method(_DBUSMENU_IFACE,
                         in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parent_id, recursion_depth, property_names):
        layout = self._build_layout(parent_id, recursion_depth, property_names)
        return dbus.UInt32(self._revision), layout

    @dbus.service.method(_DBUSMENU_IFACE,
                         in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, ids, property_names):
        result = []
        for item in self._items:
            if item["id"] in ids:
                result.append((dbus.Int32(item["id"]), self._item_props(item)))
        return result

    @dbus.service.method(_DBUSMENU_IFACE,
                         in_signature="isvu", out_signature="")
    def Event(self, id, event_id, data, timestamp):
        if event_id == "clicked":
            for item in self._items:
                if item["id"] == id and item.get("callback"):
                    try:
                        item["callback"]()
                    except Exception as e:
                        logging.error("DBusMenu callback error: %s", e)

    @dbus.service.method(_DBUSMENU_IFACE,
                         in_signature="i", out_signature="b")
    def AboutToShow(self, id):
        return False

    @dbus.service.method(_DBUSMENU_IFACE,
                         in_signature="ai", out_signature="aiai")
    def AboutToShowGroup(self, ids):
        return [], []

    @dbus.service.method(_DBUSMENU_IFACE,
                         in_signature="a(isvu)", out_signature="")
    def EventGroup(self, events):
        for id, event_id, data, timestamp in events:
            self.Event(id, event_id, data, timestamp)

    # --- DBus signals ---

    @dbus.service.signal(_DBUSMENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent):
        pass

    @dbus.service.signal(_DBUSMENU_IFACE, signature="a(ia{sv})")
    def ItemsPropertiesUpdated(self, updated_props):
        pass

    # --- DBus properties ---

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                         in_signature="ss", out_signature="v")
    def Get(self, iface, prop):
        return self.GetAll(iface)[prop]

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return {
            "Version": dbus.UInt32(3),
            "TextDirection": dbus.String("ltr"),
            "Status": dbus.String("normal"),
            "IconThemePath": dbus.Array([], signature="s"),
        }


# ---------------------------------------------------------------------------
# StatusNotifierItem  (org.kde.StatusNotifierItem)
# ---------------------------------------------------------------------------
_SNI_IFACE = "org.kde.StatusNotifierItem"
_SNW_NAME = "org.kde.StatusNotifierWatcher"
_SNW_PATH = "/StatusNotifierWatcher"


class StatusNotifierItem(dbus.service.Object):
    """GTK4-compatible system tray icon via the StatusNotifierItem D-Bus protocol.

    Usage::

        item = StatusNotifierItem("com.slimbook.service", icon_name, "Hardware")
        item.set_title("Slimbook")
        item.set_attention_icon("slimbook-status-attention-dark")
        item.set_menu([
            {"label": "Preferences", "callback": show_prefs},
            {"label": "", "type": "separator"},
            {"label": "Exit", "callback": do_exit},
        ])
        item.set_status(STATUS_ACTIVE)
    """

    def __init__(self, app_id, icon_name, category=CATEGORY_HARDWARE):
        self._bus = dbus.SessionBus()
        # Request a unique bus name so the watcher can identify us
        self._bus_name = dbus.service.BusName(
            "org.kde.StatusNotifierItem-{0}-1".format(app_id.replace(".", "-")),
            self._bus,
        )
        dbus.service.Object.__init__(self, self._bus, "/StatusNotifierItem")

        self._id = app_id
        self._category = category
        self._title = app_id
        self._status = STATUS_ACTIVE
        self._icon_name = icon_name or ""
        self._attention_icon_name = ""
        self._menu_path = dbus.ObjectPath("/MenuBar")

        self._menu = _DbusMenu(self._bus, "/MenuBar")

        self._register()

        # Re-register if the watcher restarts
        self._bus.add_signal_receiver(
            self._on_name_owner_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
            arg0=_SNW_NAME,
        )

    def _register(self):
        try:
            watcher = self._bus.get_object(_SNW_NAME, _SNW_PATH)
            watcher.RegisterStatusNotifierItem(
                self._bus_name.get_name(),
                dbus_interface=_SNW_NAME,
            )
            logging.debug("SNI registered with watcher")
        except dbus.DBusException as e:
            logging.warning("SNI watcher not available: %s", e)

    def _on_name_owner_changed(self, name, old_owner, new_owner):
        if new_owner:
            logging.debug("SNI watcher reappeared, re-registering")
            self._register()

    # --- Public API ---

    def set_title(self, title):
        self._title = title
        self.NewTitle()

    def set_icon(self, icon_name):
        self._icon_name = icon_name
        self.NewIcon()

    def set_attention_icon(self, icon_name):
        self._attention_icon_name = icon_name
        self.NewAttentionIcon()

    def set_status(self, status):
        self._status = status
        self.NewStatus(status)

    def set_menu(self, items):
        """items: list of dicts with keys label, callback, sensitive, type."""
        self._menu.set_items(items)

    # --- D-Bus methods ---

    @dbus.service.method(_SNI_IFACE, in_signature="", out_signature="")
    def Activate(self, *args):
        pass

    @dbus.service.method(_SNI_IFACE, in_signature="", out_signature="")
    def SecondaryActivate(self, *args):
        pass

    @dbus.service.method(_SNI_IFACE, in_signature="i", out_signature="")
    def Scroll(self, delta, *args):
        pass

    # --- D-Bus signals ---

    @dbus.service.signal(_SNI_IFACE)
    def NewTitle(self):
        pass

    @dbus.service.signal(_SNI_IFACE)
    def NewIcon(self):
        pass

    @dbus.service.signal(_SNI_IFACE)
    def NewAttentionIcon(self):
        pass

    @dbus.service.signal(_SNI_IFACE, signature="s")
    def NewStatus(self, status):
        pass

    @dbus.service.signal(_SNI_IFACE)
    def NewIconThemePath(self):
        pass

    # --- D-Bus properties ---

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                         in_signature="ss", out_signature="v")
    def Get(self, iface, prop):
        return self.GetAll(iface)[prop]

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                         in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return {
            "Category":          dbus.String(self._category),
            "Id":                dbus.String(self._id),
            "Title":             dbus.String(self._title),
            "Status":            dbus.String(self._status),
            "IconName":          dbus.String(self._icon_name),
            "IconPixmap":        dbus.Array([], signature="(iiay)"),
            "AttentionIconName": dbus.String(self._attention_icon_name),
            "AttentionIconPixmap": dbus.Array([], signature="(iiay)"),
            "OverlayIconName":   dbus.String(""),
            "ToolTip":           dbus.Struct(
                ["", dbus.Array([], signature="(iiay)"), self._title, ""],
                signature=None,
            ),
            "Menu":              dbus.ObjectPath(self._menu_path),
            "ItemIsMenu":        dbus.Boolean(False),
        }
