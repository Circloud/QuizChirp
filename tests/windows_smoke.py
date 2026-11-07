"""Interactive Windows acceptance check: four clicks on an owned practice surface.

Run from the project root with python -m tests.windows_smoke. The model only
receives an image if all captured pixels match the generated practice page.
"""
import ctypes
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageTk

from quizchirp import app
from quizchirp.core import Request


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    import mss
    from pynput.mouse import Controller, Button

    with mss.MSS() as sct:
        monitors = sct.monitors[1:]
        mon = next((m for m in monitors if m["left"] < 0), monitors[-1])
    w, h = mon["width"], mon["height"]
    original = Image.new("RGB", (w, h), "#fffaf1")
    draw = ImageDraw.Draw(original)
    draw.multiline_text((50, 50), "Practice question\nWhat is 17 + 6?\n\n"
                        "A. 21\nB. 22\nC. 23\nD. 24",
                        fill="black", font=ImageFont.truetype("arial.ttf", 36))
    root = tk.Tk()
    root.title("QuizChirp acceptance check")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    picture = ImageTk.PhotoImage(original)
    label = tk.Label(root, image=picture, bd=0, highlightthickness=0, cursor="none")
    label.pack()
    root.update()
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    user32.SetWindowPos(hwnd, -1, mon["left"], mon["top"], w, h, 0x40)
    root.update()
    clicks = []
    label.bind("<ButtonPress-1>", lambda e: clicks.append(e.time))
    sent = []
    outputs = []
    errors = []
    capture = app.capture

    def checked_capture(req, directory):
        path = capture(req, directory)
        with Image.open(path) as img:
            if img.size != original.size or ImageChops.difference(img.convert("RGB"), original).getbbox():
                raise AssertionError("Pixel mismatch. Upload prevented.")
        sent.append(path)
        return path

    app.capture = checked_capture
    with tempfile.TemporaryDirectory() as folder:
        tray = app.Tray(Path(folder))
        # Bypass only the physical menu click; exercise the real output stream.
        play = tray.audio.play
        def output(name):
            play(name)
            outputs.append(name)
        tray.audio.play = output
        thread = threading.Thread(target=tray.run)
        thread.start()
        controller = Controller()
        prior = controller.position

        def drive():
            try:
                deadline = time.monotonic() + 45
                while tray.status in ("Starting", "Checking Codex") and time.monotonic() < deadline:
                    time.sleep(0.2)
                assert tray.status == "Ready", tray.status
                point = (mon["left"] + 110, mon["top"] + 100)
                # Check the pixel guard before generating any mouse input.
                checked_capture(Request(0, *point, 0), Path(folder))
                sent.clear()
                controller.position = point
                handle = user32.WindowFromPoint(ctypes.c_int64((point[1] << 32) | (point[0] & 0xffffffff)))
                assert user32.GetAncestor(handle, 2) == hwnd, "Test surface not foreground"
                for _ in range(4):
                    controller.click(Button.left)
                    time.sleep(0.06)
                deadline = time.monotonic() + 310
                while not outputs and time.monotonic() < deadline:
                    if tray.status not in ("Ready", "Working"):
                        break
                    if tray.status == "Ready" and sent and not tray.gate.current:
                        time.sleep(0.5)
                        break
                    time.sleep(0.15)
                print("Displays:", len(monitors), "target origin:", mon["left"], mon["top"])
                print("Click events:", len(clicks), "captures:", len(sent), "audio:", outputs,
                      "available endpoints:", len(tray.audio.outputs), flush=True)
                assert len(clicks) == 4 and len(sent) == 1 and outputs == ["C"]
            except BaseException as exc:
                errors.append(exc)
            finally:
                controller.position = prior
                tray.quit()
                root.after(0, root.quit)

        root.after(250, lambda: threading.Thread(target=drive, daemon=True).start())
        root.mainloop()
        thread.join(15)
        root.destroy()
        if errors:
            raise errors[0]
        assert not thread.is_alive(), "Tray failed to stop"


if __name__ == "__main__":
    main()
