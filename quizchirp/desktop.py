import ctypes
import os
import subprocess
import sys
from datetime import datetime
from uuid import uuid4

import mss
from mss.tools import to_png


def open_config(path):
    if sys.platform == "win32":
        try:
            os.startfile(str(path))
        except OSError as exc:
            if exc.winerror != 1155:
                raise
            subprocess.Popen(["notepad.exe", str(path)])
    else:
        subprocess.run(["open", "-t", str(path)], check=True)


def setup_display():
    if sys.platform == "win32":
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


def click_settings():
    if sys.platform == "win32":
        api = ctypes.windll.user32
        return api.GetDoubleClickTime() / 1000, (
            max(1, api.GetSystemMetrics(36) // 2), max(1, api.GetSystemMetrics(37) // 2))
    from AppKit import NSEvent
    # AppKit exposes the click interval; compare positions in display points.
    return NSEvent.doubleClickInterval(), (4, 4)


def permissions(request=False, input_only=False):
    if sys.platform != "darwin":
        return True
    import Quartz
    checks = [(Quartz.CGPreflightListenEventAccess, Quartz.CGRequestListenEventAccess)]
    if not input_only:
        checks.append((Quartz.CGPreflightScreenCaptureAccess, Quartz.CGRequestScreenCaptureAccess))
    for check, ask in checks:
        if not check() and not (request and ask()):
            return False
    return True


def capture(request, directory):
    with mss.MSS() as screen:
        for monitor in screen.monitors[1:]:
            left, top = monitor["left"], monitor["top"]
            if (left <= request.x < left + monitor["width"]
                    and top <= request.y < top + monitor["height"]):
                shot = screen.grab(monitor)
                break
        else:
            raise OSError("The display at the click position is unavailable.")
    name = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex}.png"
    path = directory / name
    path.write_bytes(to_png(shot.rgb, shot.size))
    return path


def check_capture(request, directory):
    """Verify the failed capture/save operation locally without retaining an image."""
    path = capture(request, directory)
    path.unlink()
