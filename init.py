# TODO: Sort these imports
import os
import time
import logging
import threading

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("pything")

os.chdir(os.path.dirname(os.path.abspath(__file__))) # sanity check

serial_cache = {}
# {SERIAL: [ISTHING, WASINJECTED]}

# Determine whether to show command output
#show_output = logger.isEnabledFor(logging.DEBUG)
show_output = True
# Car Thing injection stuff
def is_carthing_serial(serial):
    if serial in serial_cache:
        return serial_cache[serial][0]
    check_command = f"adb -s {serial} shell '[ -d /usr/share/qt-superbird-app/webapp/ ] && echo exists'"
    result = os.popen(check_command).read().strip()
    if result == "exists":
        logger.info(f"Found device {serial}")
        serial_cache[serial] = [True, False]
        return True
    else:
        serial_cache[serial] = [False, False]
        return False

def get_carthings():
    connected_devices = os.popen("adb devices").read().strip().splitlines()[1:]
    things = []
    for device in connected_devices:
        if device.strip():
            serial_num = device.split()[0]
            if is_carthing_serial(serial_num):
                things.append(serial_num)
    return things

def inject_thread():
    while True:
        connected = get_carthings()
        # Remove disconnected devices
        for serial in list(serial_cache.keys()):
            if serial not in connected:
                logger.info(f"{serial} disconnected")
                del serial_cache[serial]
        # Initialize newly connected devices
        for serial in connected:
            if serial_cache[serial][1]:
                continue
            if os.system("./ctsetup.sh " + serial + (" >/dev/null 2>&1" if not show_output else "")) == 0:
                serial_cache[serial][1] = True
            else:
                logger.error("Car Thing setup failed.")
        time.sleep(2)

threading.Thread(target=inject_thread, daemon=True).start()

time.sleep(60)