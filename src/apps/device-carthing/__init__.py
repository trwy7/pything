import os
import threading
import subprocess
import time
import platform
import pathlib
import tempfile
import shutil
import zipfile
import urllib.request
from init import App

app = App("Carthing connector", [])

adb = False

# Save time so we dont check for the superbird webapp directory every adb pass
serial_cache = {}

# Install adb for people who do not already have it
def ensure_adb(r=False):
    if os.system("adb devices") == 0:
        return True
    if os.path.isdir(os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools"))):
        os.environ["PATH"] = os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools")) + os.pathsep + os.environ.get("PATH", "")
        if os.system("adb devices") == 0:
            return True
        app.logger.warning("%s exists and does not contain a valid ADB install. Car thing integration will not work until you rename or remove it.", os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools")))
        return False
    if r:
        return False
    res = input("Could not find ADB in your path. ADB is required for Car Thing connection, but is not required otherwise. Would you like to download it automatically [y/N]?")
    if res.lower() == "y":
        system = platform.system().lower()
        urls = {
            "windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
            "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
            "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
        }
        if system not in urls:
            app.logger.error("System not supported, continuing without ADB")
            return False
        with tempfile.TemporaryDirectory() as tempdir:
            zpath = os.path.join(tempdir, "t.zip")
            urllib.request.urlretrieve(urls[system], zpath)
            with zipfile.ZipFile(zpath, 'r') as zip:
                zip.extractall(tempdir)
            os.remove(zpath)
            shutil.move(os.path.join(tempdir, "platform-tools"), pathlib.Path.home())
        if system != "windows":
            os.system(f"chmod +x '{os.path.join(pathlib.Path.home(), "platform-tools", "adb")}'")
        app.logger.info("ADB has been downloaded to %s", os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools")))
        return ensure_adb(r=True)
    return False

def run_adb_cmd(serial: str, command: list[str]):
    if not adb:
        app.logger.warning("An adb command was ran, but adb has not been validated")
        return
    cmd = ["adb", "-s", serial]
    cmd.extend(command)
    app.logger.debug("[%s] + %s", serial, " ".join(cmd))
    cmd_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    for out in cmd_proc.stdout.readlines(): # type: ignore
        app.logger.debug("[%s] %s", serial, out)
    while cmd_proc.poll() is None:
        time.sleep(0.2)
    return cmd_proc.returncode

# Make sure we don't run commands on a random device
def is_carthing_serial(serial: str):
    if serial in serial_cache:
        return serial_cache[serial][0]
    result = subprocess.run(
        ["adb", "-s", serial, "shell", "[ -d /usr/share/qt-superbird-app/webapp/ ] && echo exists"],
        capture_output=True,
        text=True
    ).stdout.strip()
    if result == "exists":
        app.logger.debug(f"Found device {serial}")
        serial_cache[serial] = [True, False]
        return True
    else:
        app.logger.debug("Device %s is not a superbird", serial)
        serial_cache[serial] = [False, False]
        return False

# Get a list of connected carthings
def get_carthings():
    connected_devices = os.popen("adb devices").read().strip().splitlines()[1:]
    things = []
    for device in connected_devices:
        if device.strip():
            serial_num = device.split()[0]
            if is_carthing_serial(serial_num):
                things.append(serial_num)
    return things

# Background process to bind mount ctroot
def inject_thread():
    while True:
        connected = get_carthings()
        # Remove disconnected devices
        for serial in list(serial_cache.keys()):
            if serial not in connected:
                if serial_cache[serial][0]:
                    app.logger.info(f"{serial} disconnected")
                    del serial_cache[serial]
        # Initialize newly connected devices
        for serial in connected:
            if serial_cache[serial][1]:
                continue
            ct_connect = False
            run_adb_cmd(serial, ['reverse', 'tcp:5192', 'tcp:5192'])
            if os.popen(f"adb -s {serial} shell '[ -f /usr/share/qt-superbird-app/webapp/pythingclient2.txt ] && echo exists'").read().strip() == "exists":
                app.logger.debug("No need to repush webapp for %s", serial)
                serial_cache[serial][1] = True
                continue
            run_adb_cmd(serial, ['shell', 'supervisorctl stop chromium'])
            restore_ct_webapp(fserial=serial, restart=False)
            run_adb_cmd(serial, ['shell', 'rm -rf /tmp/ptwebapp'])
            run_adb_cmd(serial, ['push', f'apps/{app.dirname}/ctroot', '/tmp/ptwebapp'])
            run_adb_cmd(serial, ['shell', 'mount --bind /tmp/ptwebapp /usr/share/qt-superbird-app/webapp'])
            run_adb_cmd(serial, ['shell', 'supervisorctl start chromium'])
            serial_cache[serial][1] = True
        time.sleep(2)

# Restore carthing webapp from a temporary inject
def restore_ct_webapp(fserial: str | None=None, restart: bool=True):
    for serial in get_carthings() if fserial is None else [fserial]:
        if is_carthing_serial(serial):
            app.logger.info(f"Restoring {serial}...")
            run_adb_cmd(serial, ['shell', 'mountpoint /usr/share/qt-superbird-app/webapp/ > /dev/null && umount /usr/share/qt-superbird-app/webapp'])
            if restart:
                run_adb_cmd(serial, ['shell', 'supervisorctl', 'restart', 'chromium'])

# Fully replace the original webapp with ptclient
def full_replace_carthing(serials: list | None=None):
    """If used, gives faster app startup times from a restart"""
    if serials is None:
        serials = get_carthings()
    for serial in serials:
        restore_ct_webapp(fserial=serial, restart=False)
        app.logger.info("Replacing %s...", serial)
        run_adb_cmd(serial, ['shell', 'mount -o remount,rw /'])
        run_adb_cmd(serial, ['shell', 'rm -rf /usr/share/qt-superbird-app/webapp'])
        run_adb_cmd(serial, ['push', f'apps/{app.dirname}/ctroot', '/usr/share/qt-superbird-app/webapp'])
        run_adb_cmd(serial, ['shell', 'supervisorctl', 'restart', 'chromium'])
        run_adb_cmd(serial, ['shell', 'mount -o remount,ro /'])

adb = ensure_adb()
if adb:
    threading.Thread(target=inject_thread, daemon=True).start()
else:
    app.logger.warning("ADB is not available, the carthing will not be able to connect.")
