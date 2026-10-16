import asyncio
import os
import sys
import threading

from init import App, BooleanSetting, socket

app = App(
    "Extras",
    [BooleanSetting("lockstate", "Hide the display when the screen is locked", True)],
    category="system",
)

app.screenlockstate = False
listener_lock = threading.Lock()
listener_thread: threading.Thread | None = None
listener_stop_event: threading.Event | None = None


def update_lock_state(locked: bool) -> None:
    if locked == app.screenlockstate:
        return
    app.screenlockstate = locked
    app.logger.debug("Screen lock state: %s", locked)
    socket.emit("addons_lockstate", locked)


async def linux_lock_loop(stop_event: threading.Event) -> None:
    from dbus_next import BusType
    from dbus_next.aio import MessageBus

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    manager = await bus.introspect("org.freedesktop.login1", "/org/freedesktop/login1")
    manager_object = bus.get_proxy_object(
        "org.freedesktop.login1", "/org/freedesktop/login1", manager
    )
    manager_interface = manager_object.get_interface("org.freedesktop.login1.Manager")
    session_id = os.environ.get("XDG_SESSION_ID")
    if not session_id:
        raise RuntimeError("XDG_SESSION_ID is not set")

    session_path = await manager_interface.call_get_session(session_id)
    session = await bus.introspect("org.freedesktop.login1", session_path)
    session_object = bus.get_proxy_object(
        "org.freedesktop.login1", session_path, session
    )
    properties = session_object.get_interface("org.freedesktop.DBus.Properties")

    def on_properties_changed(interface_name, changed, _invalidated) -> None:
        if (
            interface_name == "org.freedesktop.login1.Session"
            and "LockedHint" in changed
        ):
            update_lock_state(changed["LockedHint"].value)

    properties.on_properties_changed(on_properties_changed)
    update_lock_state(
        (
            await properties.call_get("org.freedesktop.login1.Session", "LockedHint")
        ).value
    )
    await asyncio.to_thread(stop_event.wait)
    bus.disconnect()


def windows_lock_loop(stop_event: threading.Event) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    WM_WTSSESSION_CHANGE = 0x02B1
    WTS_SESSION_LOCK = 0x7
    WTS_SESSION_UNLOCK = 0x8
    NOTIFY_FOR_THIS_SESSION = 0
    HWND_MESSAGE = wintypes.HWND(-3)
    class_name = "PythingLockStateWindow"

    wnd_proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", wnd_proc_type),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HANDLE,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
    wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
    wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
    wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL

    @wnd_proc_type
    def window_proc(hwnd, message, wparam, lparam):
        if message == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                update_lock_state(True)
            elif wparam == WTS_SESSION_UNLOCK:
                update_lock_state(False)
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    hinstance = kernel32.GetModuleHandleW(None)
    window_class = WNDCLASSW(
        lpfnWndProc=window_proc, hInstance=hinstance, lpszClassName=class_name
    )
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        raise ctypes.WinError(ctypes.get_last_error())

    hwnd = user32.CreateWindowExW(
        0,
        class_name,
        "Pything lock state listener",
        0,
        0,
        0,
        0,
        0,
        HWND_MESSAGE,
        None,
        hinstance,
        None,
    )
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    if not wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
        raise ctypes.WinError(ctypes.get_last_error())

    thread_id = kernel32.GetCurrentThreadId()
    stop_watcher = threading.Thread(
        target=lambda: (
            stop_event.wait(),
            user32.PostThreadMessageW(thread_id, 0x0012, 0, 0),
        ),
        daemon=True,
    )
    stop_watcher.start()
    try:
        message = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(message), hwnd, 0, 0)
            if result == -1:
                raise ctypes.WinError(ctypes.get_last_error())
            if result == 0:
                break
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
    finally:
        stop_event.set()
        stop_watcher.join()
        wtsapi32.WTSUnRegisterSessionNotification(hwnd)
        user32.DestroyWindow(hwnd)


def lock_thread(stop_event: threading.Event) -> None:
    if sys.platform == "linux":
        try:
            asyncio.run(linux_lock_loop(stop_event))
        except ModuleNotFoundError:
            app.logger.warning(
                "Screen lock tracking requires the dbus-next package on Linux"
            )
        except (OSError, RuntimeError):
            app.logger.debug("Failed to subscribe to screen lock state", exc_info=True)
    elif sys.platform == "win32":
        try:
            windows_lock_loop(stop_event)
        except OSError:
            app.logger.debug("Failed to subscribe to screen lock state", exc_info=True)


def stop_lock_listener() -> None:
    global listener_thread, listener_stop_event
    with listener_lock:
        thread = listener_thread
        stop_event = listener_stop_event
        listener_thread = None
        listener_stop_event = None
    if stop_event is not None:
        stop_event.set()
    if thread is not None and thread is not threading.current_thread():
        thread.join()


def start_lock_listener() -> None:
    global listener_thread, listener_stop_event
    if (
        sys.platform not in ("win32", "linux")
        or not app.settings["lockstate"].get_value()
    ):
        return
    with listener_lock:
        if listener_thread is not None and listener_thread.is_alive():
            return
        listener_stop_event = threading.Event()
        listener_thread = threading.Thread(
            target=lock_thread, args=(listener_stop_event,), daemon=True
        )
        listener_thread.start()


@app.on_setting_update
def update_lock_listener() -> None:
    stop_lock_listener()
    if app.settings["lockstate"].get_value():
        start_lock_listener()
    else:
        update_lock_state(False)


@app.on_startup
def start_addon_threads() -> None:
    start_lock_listener()
