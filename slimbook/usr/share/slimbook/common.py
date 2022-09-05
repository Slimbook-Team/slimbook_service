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

import os, codecs, json
import locale
import gettext

PARAMS = {
            'first-time': True,
            'version': '',
            'autostart': True,
            'theme': 'light',
            'show': True
            }

APP = 'slimbook'
VERSION = '0.1'
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

def is_package():
    return os.path.abspath(os.path.dirname(__file__)).startswith('/usr')

if is_package():
    APPDIR = '/usr/share/slimbook'
else:
    APPDIR = os.path.abspath(os.path.join('..', os.path.dirname(os.path.realpath(__file__))))

print('Config = '+CONFIG_FILE)

LANGDIR = os.path.join(APPDIR, 'locale-langpack')
ICONDIR = os.path.join(APPDIR, 'icons')
FILE_AUTO_START_ORIG = os.path.join(APPDIR,
                                    'slimbook-client-autostart.desktop')

ICONDIR = os.path.join(APPDIR, 'icons')
ICON = os.path.join(ICONDIR, 'slimbook_be1ofus_light.svg')

STATUS_ICON = {}
STATUS_ICON['light'] = (os.path.join(ICONDIR, 'slimbook_be1ofus_light.svg'))
STATUS_ICON['dark'] = (os.path.join(ICONDIR, 'slimbook_be1ofus_dark.svg'))

try:
    current_locale, encoding = locale.getdefaultlocale()
    language = gettext.translation(APP, LANGDIR, [current_locale])
    language.install()
    _ = language.gettext
except Exception as e:
    _ = str

# print(os.path.dirname(os.path.abspath(__file__)))

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