#!/usr/bin/python3
import subprocess
import evdev
import os
import logging
import getpass

logger = logging.getLogger("main")
logging.basicConfig(format='%(levelname)s-%(message)s')
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)


def get_user():
    user_name = None
    try:
        user_name = getpass.getuser()
    except Exception as e:
        logger.error(e)

    if user_name == None or user_name == 'root':
        if 'SUDO_USER' in os.environ and os.environ['SUDO_USER'] != 'root':
            user_name = os.environ['SUDO_USER']
        else:
            logger.debug('last case')
            user_name = None
            user_names = subprocess.getoutput(
                'last -wn10 | head -n 10 | cut -f 1 -d " "').split('\n')

            for n in range(len(user_names)-1):
                user_name = user_names[n]
                logger.debug(user_name)
                if user_name != 'reboot':
                    logger.info("Username: {}".format(user_name))
                    break
    return user_name


user = get_user()
uid = subprocess.getoutput("id -u {}".format(user))
logger.debug(uid + " " + user)
logger.debug(subprocess.getoutput("groups"))

qc71_dirname = '/sys/devices/platform/qc71_laptop'
QC71_mod_loaded = True if os.path.isdir(qc71_dirname) else False


def notify_send(msg):
    print(user)
    command = "su {} -c \"notify-send -t 500 -u low 'Slimbook Notification' '{}'\"".format(
        user, msg)
    os.system(command)


def detect_touchpad():
    touchpad_device = None
    for file in os.listdir('/dev'):
        if file.startswith('hidraw'):
            logger.debug(file)
            data_file = '/sys/class/hidraw/{file}/device/uevent'.format(
                file=file)
            logger.debug(data_file)
            for line in open(data_file).readlines():
                if line.startswith('HID_NAME=') and line.find('UNIW0001:00 093A:') != -1:
                    try:
                        logger.debug('Found keyboard at: ' +
                                     '/dev/{}'.format(file))
                        touchpad_device = open('/dev/{}'.format(file), 'r')
                    except Exception as e:
                        logger.error(e)
    return touchpad_device


def detect_keyboard():
    keyboard_device_path = None
    for file in os.listdir('/dev/input/by-path'):
        if file.endswith('event-kbd') and file.find('i8042') != -1:
            file_path = os.path.join('/dev/input/by-path', file)
            keyboard_device_path = os.path.realpath(
                os.path.join(file_path, os.readlink(file_path)))
            logger.debug('Found keyboard at: ' + keyboard_device_path)
    return keyboard_device_path


device = evdev.InputDevice(detect_keyboard())
DEV = detect_touchpad()
EVENTS = {
    104: {
        "key": "F2",
        "msg": {0: "Super Key Lock disabled", 1: "Super Key Lock enabled", 'default': "Super Key Lock state changed"},
        "type": "",
    },
    105: {
        "key": "F5",
        "msg": {0: "Silent Mode disabled", 1: "Silent Mode enabled", 'default': "Silent Mode state changed"},
        "type": "",
    },
    118: {
        "key": "Touchpad button",
        "msg": {0: "Touchpad disabled", 1: "Touchpad enabled", 'default': "Touchpad state changed"},
        "type": "",
    },
}

last_event = 0
send_notification = None

for event in device.read_loop():
    if event.type == evdev.ecodes.EV_MSC:
        if event.value != last_event:
            state_int = None
            if event.value == 104:
                send_notification = True
                if QC71_mod_loaded:
                    qc71_filename = '/sys/devices/platform/qc71_laptop/silent_mode'
                    file = open(qc71_filename, mode='r')
                    content = file.read()
                    # line = file.readline()
                    file.close()
                    try:
                        state_int = int(content)
                    except:
                        logger.error("Silent mode state read error")
                else:
                    logger.info('qc71_laptop not loaded')

            elif event.value == 105:
                send_notification = True

                if QC71_mod_loaded:
                    qc71_filename = '/sys/devices/platform/qc71_laptop/silent_mode'
                    file = open(qc71_filename, mode='r')
                    content = file.read()
                    # line = file.readline()
                    file.close()
                    try:
                        state_int = int(content)
                    except:
                        logger.error("Silent mode state read error")

                else:
                    logger.info('qc71_laptop not loaded')

            elif event.value == 118:
                from fcntl import ioctl
                HIDIOCSFEATURE = 0xC0024806  # 2bytes
                HIDIOCGFEATURE = 0xC0024807  # 2bytes
                STATES = {
                    0: {
                        "bytes": bytes([0x07, 0x00]),
                        "action": 1,
                        "msg": "Disabled",
                    },
                    1: {
                        "bytes": bytes([0x07, 0x03]),
                        "action": 0,
                        "msg": "Enabled",
                    },
                }
                try:
                    status = ioctl(DEV, HIDIOCGFEATURE, bytes([0x07, 0]))
                    current_status = str(status)
                    # Setting state_int value != NONE we choose the notification according to the device state.
                    state_int = 1 if current_status.find("x00") != -1 else 0
                    logger.debug(str(state_int) + " " + str(current_status))
                except Exception as e:
                    logger.error(e)

                try:
                    ioctl(DEV, HIDIOCSFEATURE, STATES.get(
                        int(state_int)).get("bytes"))
                except Exception as e:
                    logger.error(e)

                send_notification = True

            last_event = event.value
            if EVENTS.get(event.value):
                msg = (
                    ((EVENTS.get(event.value)).get("msg")).get(state_int)
                    if state_int != None
                    else EVENTS.get(event.value).get("msg").get('default')
                )
                if send_notification:
                    logger.info("Should notify " + str(msg))
                    notify_send(msg)
                else:
                    logger.debug(send_notification)
