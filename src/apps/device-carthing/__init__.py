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
from init import App, BooleanSetting

app = App(
    [BooleanSetting("adb", "Ask to download ADB", True), BooleanSetting("lockdisplay", "Turn off the display when the screen is locked (requires display hiding to be enabled in the addons app)", True)]
)

adb = False

# Save time so we dont check for the superbird webapp directory every adb pass
serial_cache = {}
ADB = "adb"

def check_adb():
    if shutil.which(ADB) is None:
        return False
    try:
        res = subprocess.run(
            [ADB, "devices"], capture_output=True, timeout=2, check=False
        )
        return res.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

# Install adb for people who do not already have it
def ensure_adb(r=False):
    if check_adb():
        return True
    if os.path.isdir(
        os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools"))
    ):
        os.environ["PATH"] = (
            os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools"))
            + os.pathsep
            + os.environ.get("PATH", "")
        )
        if check_adb():
            return True
        app.logger.warning(
            "%s exists and does not contain a valid ADB install. Car thing integration will not work until you rename or remove it.",
            os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools")),
        )
        return False
    if r:
        return False
    if not app.settings["adb"].get_value():
        return False
    res = input(
        "Could not find ADB in your path. ADB is required for Car Thing connection, but is not required otherwise. Would you like to download it automatically [y/N]?"
    )
    if res.lower() == "y":
        system = platform.system().lower()
        urls = {
            "windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
            "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
            "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
        }
        if system not in urls:
            app.logger.error("System not supported, continuing without ADB")
            return False
        with tempfile.TemporaryDirectory() as tempdir:
            zpath = os.path.join(tempdir, "t.zip")
            urllib.request.urlretrieve(urls[system], zpath)
            with zipfile.ZipFile(zpath, "r") as zip:
                zip.extractall(tempdir)
            os.remove(zpath)
            shutil.move(os.path.join(tempdir, "platform-tools"), pathlib.Path.home())
        if system != "windows":
            adb_path = pathlib.Path.home() / "platform-tools" / "adb"
            adb_path.chmod(adb_path.stat().st_mode | 0o111)
        app.logger.info(
            "ADB has been downloaded to %s",
            os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools")),
        )
        return ensure_adb(r=True)
    elif res.lower() == "n":
        app.settings["adb"].set_value(False)
    return False


def run_adb_cmd(serial: str, command: list[str]):
    if not adb:
        app.logger.warning("An adb command was ran, but adb has not been validated")
        return
    cmd = [ADB, "-s", serial]
    cmd.extend(command)
    app.logger.debug("[%s] + %s", serial, " ".join(cmd))
    cmd_proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    output, _ = cmd_proc.communicate()
    for out in output.splitlines():
        app.logger.debug("[%s] %s", serial, out)
    return cmd_proc.returncode


def run_adb_query(serial: str, command: list[str], timeout: float = 3) -> str:
    try:
        result = subprocess.run(
            [ADB, "-s", serial, *command],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


# Make sure we don't run commands on a random device
def is_carthing_serial(serial: str) -> bool:
    if serial in serial_cache:
        return serial_cache[serial][0]

    # Combine file/directory checks into one remote command
    check_cmd = "[ -d /usr/share/qt-superbird-app/webapp/ ] && echo 'webapp' || ([ -f /etc/superbird ] && grep -q 'Bridgething' /etc/superbird && echo 'bridgething')"
    result = run_adb_query(serial, ["shell", check_cmd])

    if "webapp" in result:
        app.logger.debug(f"Found device {serial}")
        serial_cache[serial] = [True, False, False]
        return True
    elif "bridgething" in result:
        app.logger.debug("Device %s is a superbird (bridgething)", serial)
        serial_cache[serial] = [True, False, True]
        return True

    app.logger.debug("Device %s is not a superbird", serial)
    serial_cache[serial] = [False, False, False]
    return False


# Get a list of connected carthings
def get_carthings():
    try:
        result = subprocess.run(
            [ADB, "devices"], capture_output=True, text=True, timeout=2, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    connected_devices = result.stdout.splitlines()[1:]
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
            run_adb_cmd(serial, ["reverse", "tcp:5192", "tcp:5192"])
            if serial_cache[serial][2]:
                app.logger.debug("No need to push webapp for %s (bridgething)", serial)
                app.logger.info(
                    "Bridgething detected for %s, you may want to bookmark http://127.0.0.1:5192?device=bridgething in the browser",
                    serial,
                )
                serial_cache[serial][1] = True
                continue
            if run_adb_query(
                serial,
                [
                    "shell",
                    "[ -f /usr/share/qt-superbird-app/webapp/pythingclient2.txt ] && echo exists",
                ],
            ) == "exists":
                app.logger.debug("No need to repush webapp for %s", serial)
                serial_cache[serial][1] = True
                continue
            run_adb_cmd(serial, ["shell", "supervisorctl stop chromium"])
            restore_ct_webapp(fserial=serial, restart=False)
            run_adb_cmd(serial, ["shell", "rm -rf /tmp/ptwebapp"])
            run_adb_cmd(serial, ["push", f"apps/{app.dirname}/ctroot", "/tmp/ptwebapp"])
            run_adb_cmd(
                serial,
                [
                    "shell",
                    "mount --bind /tmp/ptwebapp /usr/share/qt-superbird-app/webapp",
                ],
            )
            run_adb_cmd(serial, ["shell", "supervisorctl start chromium"])
            serial_cache[serial][1] = True
        time.sleep(2)


# Restore carthing webapp from a temporary inject
def restore_ct_webapp(fserial: str | None = None, restart: bool = True):
    for serial in get_carthings() if fserial is None else [fserial]:
        if is_carthing_serial(serial):
            app.logger.info(f"Restoring {serial}...")
            run_adb_cmd(
                serial,
                [
                    "shell",
                    "mountpoint /usr/share/qt-superbird-app/webapp/ > /dev/null && umount /usr/share/qt-superbird-app/webapp",
                ],
            )
            if restart:
                run_adb_cmd(serial, ["shell", "supervisorctl", "restart", "chromium"])


# Fully replace the original webapp with ptclient
def full_replace_carthing(serials: list | None = None):
    """If used, gives faster app startup times from a restart"""
    if serials is None:
        serials = get_carthings()
    for serial in serials:
        restore_ct_webapp(fserial=serial, restart=False)
        app.logger.info("Replacing %s...", serial)
        run_adb_cmd(serial, ["shell", "mount -o remount,rw /"])
        run_adb_cmd(serial, ["shell", "rm -rf /usr/share/qt-superbird-app/webapp"])
        run_adb_cmd(
            serial,
            [
                "push",
                f"apps/{app.dirname}/ctroot",
                "/usr/share/qt-superbird-app/webapp",
            ],
        )
        run_adb_cmd(serial, ["shell", "supervisorctl", "restart", "chromium"])
        run_adb_cmd(serial, ["shell", "mount -o remount,ro /"])

@app.on_broadcast("lockstate")
def on_lock(lock: bool):
    if not app.settings["lockdisplay"].get_value():
        return
    if lock:
        # Turn off screens of all connected carthings
        for serial in get_carthings():
            run_adb_cmd(serial, ["shell", "supervisorctl stop backlight"])
            run_adb_cmd(serial, ["shell", "echo 0 > /sys/class/backlight/aml-bl/brightness"])
    else:
        # Turn on screens of all connected carthings
        for serial in get_carthings():
            run_adb_cmd(serial, ["shell", "echo 240 > /sys/class/backlight/aml-bl/brightness"]) # this is actually dark, but the backlight service will automatically brighten it again
            run_adb_cmd(serial, ["shell", "supervisorctl start backlight"])

adb = ensure_adb()
if adb:
    threading.Thread(
        target=inject_thread, daemon=True
    ).start()  # start as soon as possible without waiting for other apps
else:
    app.logger.warning(
        "ADB is not available, the carthing will not be able to connect."
    )
