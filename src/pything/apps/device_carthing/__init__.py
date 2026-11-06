import os
import pathlib
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile

from pything import CACHE_ROOT, App, BooleanSetting

app = App(
    [
        BooleanSetting(
            "lockdisplay",
            "Turn off the display when the screen is locked (requires the Extras app and display hiding)",
            True,
        ),
    ]
)

adb = False

# Save time so we dont check for the superbird webapp directory every adb pass
serial_cache = {}
adb_path = "adb"


def check_adb():
    shadb = shutil.which("adb")
    if shadb is None:
        app.logger.debug("ADB not found in PATH")
        return False
    try:
        app.logger.debug("Checking ADB at PATH: %s", shadb)
        res = subprocess.run(
            [shadb, "devices"], capture_output=True, timeout=10, check=False
        )
        if res.returncode == 0:
            app.logger.debug("ADB found in PATH")
            global adb_path
            adb_path = shadb
            return True
        app.logger.debug(
            "ADB found in PATH, but returned non-zero exit code: %s", res.returncode
        )
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        app.logger.debug("ADB not found or timed out: %s", str(e))
        return False


# Install adb for people who do not already have it
def ensure_adb(r=False):
    if check_adb():
        return True
    platform_tools_dirs = [
        os.path.abspath(os.path.join(CACHE_ROOT, "pything", "platform-tools")),
        os.path.abspath(os.path.join(pathlib.Path().home(), "platform-tools")),
    ]
    for platform_tools_dir in platform_tools_dirs:
        if os.path.isdir(platform_tools_dir):
            os.environ["PATH"] = (
                platform_tools_dir + os.pathsep + os.environ.get("PATH", "")
            )
            if check_adb():
                return True
            app.logger.warning(
                "%s exists, but does not contain a valid ADB install.",
                platform_tools_dir,
            )
    if r or os.path.exists(os.path.join(CACHE_ROOT, "pything", "platform-tools")):
        return False
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
        shutil.move(
            os.path.join(tempdir, "platform-tools"),
            pathlib.Path(CACHE_ROOT) / "pything" / "platform-tools",
        )
    if system != "windows":
        global adb_path
        adb_path = pathlib.Path(CACHE_ROOT) / "pything" / "platform-tools" / "adb"
        adb_path.chmod(adb_path.stat().st_mode | 0o111)
    app.logger.info(
        "ADB has been downloaded to %s",
        os.path.abspath(os.path.join(CACHE_ROOT, "pything", "platform-tools")),
    )
    return ensure_adb(r=True)


def run_adb_cmd(serial: str, command: list[str]):
    if not adb_path:
        app.logger.warning("An adb command was ran, but adb has not been validated")
        return
    cmd = [adb_path, "-s", serial]
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
            [adb_path, "-s", serial, *command],
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
            [adb_path, "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
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
            if serial not in connected and serial_cache[serial][0]:
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
            if (
                run_adb_query(
                    serial,
                    [
                        "shell",
                        "[ -f /usr/share/qt-superbird-app/webapp/pythingclient2.txt ] && echo exists",
                    ],
                )
                == "exists"
            ):
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
            run_adb_cmd(
                serial, ["shell", "echo 0 > /sys/class/backlight/aml-bl/brightness"]
            )
    else:
        # Turn on screens of all connected carthings
        for serial in get_carthings():
            run_adb_cmd(
                serial, ["shell", "echo 240 > /sys/class/backlight/aml-bl/brightness"]
            )  # this is actually dark, but the backlight service will automatically brighten it again
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
