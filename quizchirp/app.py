import asyncio
import logging
import sys
import threading
import time
import webbrowser
from contextlib import suppress
from pathlib import Path
from logging.handlers import RotatingFileHandler

from .desktop import setup_display

setup_display()

from filelock import FileLock, Timeout
from PIL import Image
from pynput import mouse
from pystray import Icon, Menu, MenuItem as Item

from .audio import Audio
from .core import Gate
from .config import Settings
from .paths import prepare_data_directory
from . import runtime
from .i18n import Translator
from .desktop import capture, check_capture, click_settings, permissions, open_config
from .answers import ANSWERS, CHOICES
from .engine import Engine, ACCESS_UNVERIFIED

LOG = logging.getLogger(__name__)
SCREEN_ACCESS_REQUIRED = "Allow screen access, then trigger again"
INPUT_ACCESS_REQUIRED = "Allow input access, then retry; restart if needed"
RUNTIME_IDLE = ("No compatible Codex found", "Codex preparation failed")
RETRYABLE_STATUSES = (*RUNTIME_IDLE, INPUT_ACCESS_REQUIRED, SCREEN_ACCESS_REQUIRED,
                      "Usage limit reached", "Connection unavailable", "Request failed",
                      ACCESS_UNVERIFIED, "Sign-in required")

if sys.platform == "win32":
    from pystray._util import win32

    class DesktopIcon(Icon):
        """Rebuild native menus on the thread that owns their window."""

        refresh_message = win32.WM_USER + 32

        def __init__(self, *args):
            super().__init__(*args)
            self._message_handlers[self.refresh_message] = self._refresh

        def _refresh(self, wparam, lparam):
            self.update_menu()

        def schedule_menu_update(self):
            win32.PostMessage(self._hwnd, self.refresh_message, 0, 0)

else:
    class DesktopIcon(Icon):
        def schedule_menu_update(self):
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self.update_menu)


def icon_image():
    with Image.open(Path(__file__).with_name("assets") / "tray.png") as image:
        return image.resize((64, 64), Image.Resampling.LANCZOS)


def error_status(exc):
    message = str(exc).lower()
    if any(s in message for s in ("401", "unauthorized", "sign in", "authentication", "token expired")):
        return "Sign-in required"
    if any(s in message for s in ("429", "usage limit", "rate limit", "quota")):
        return "Usage limit reached"
    if any(s in message for s in ("network", "connection", "transport", "connect", "timed out")):
        return "Connection unavailable"
    return "Request failed"


class Tray:
    def __init__(self, directory):
        self.directory = directory
        self.settings = Settings.load(directory)
        self.text = Translator(self.settings.language)
        logging.getLogger().setLevel(self.settings.log_level)
        LOG.info("Starting QuizChirp data=%s log_level=%s", directory, self.settings.log_level)
        self.shots = directory / "screenshots"
        self.shots.mkdir(exist_ok=True)
        self.engine = None
        self.runtime_task = None
        self.runtime_cancel = threading.Event()
        self.runtime_progress = None
        self.runtime_error = None
        self.audio = Audio(directory, self.settings)
        self.gate = Gate(*click_settings(), timeout=self.settings.timeout_seconds,
                         trigger_mode=self.settings.trigger_mode)
        self.icon = DesktopIcon("QuizChirp", icon_image(), self.text("QuizChirp"))
        self.status = "Starting"
        self.listener = None
        self.login = None
        self.request_task = None
        self.check_task = None
        self.failed_operation = None
        self.pending_screenshots = []
        self.loop = asyncio.new_event_loop()
        self.stop_event = asyncio.Event()
        self.menu_live = False
        self.closed = False
        self.icon.menu = Menu(self.items)
        self.worker = threading.Thread(target=self.work, name="quizchirp-worker")

    def action(self, function, *args):
        def invoke(icon, item):
            if not self.closed:
                future = asyncio.run_coroutine_threadsafe(function(*args), self.loop)
                future.add_done_callback(lambda done: self.action_done(done, function, args))
        return invoke

    def action_done(self, future, function=None, args=()):
        if not future.cancelled() and future.exception() and not self.closed:
            LOG.error("Tray action failed: %s", type(future.exception()).__name__)
            if (self.check_task is not None or self.gate.current is not None
                    or self.status in ("Starting", "Working", "Waiting for sign-in")):
                return
            if self.engine is None:
                self.runtime_error = "Check connection, disk space and runtime path"
                self.set_status("Codex preparation failed")
                return
            if function and function.__name__ in ("open_configuration", "select_audio", "select_trigger"):
                self.failed_operation = ("action", (function, args))
            else:
                self.failed_operation = ("unknown", None)
            self.set_status(error_status(future.exception()))

    def items(self):
        text = self.text
        label = text(self.status)
        if self.status == "Downloading Codex" and self.runtime_progress is not None:
            label += f" · {self.runtime_progress}%"
        yield Item(label, None, enabled=False)
        if self.status in RUNTIME_IDLE:
            if self.runtime_error:
                yield Item(text(self.runtime_error), None, enabled=False)
            yield Item(text("Download Codex"), self.action(self.download_runtime))
        if self.status in ("Downloading Codex", "Preparing Codex"):
            yield Item(text("Cancel download"), self.action(self.cancel_runtime))
        if self.status == "Sign-in required":
            yield Item(text("Sign in with ChatGPT..."), self.action(self.sign_in))
        if self.status == "Waiting for sign-in":
            yield Item(text("Cancel"), self.action(self.cancel_login))
        if self.status in RETRYABLE_STATUSES:
            yield Item(text("Retry"), self.action(self.recheck))
        names = [(text("System default"), None)] + [(name, name) for name in self.audio.outputs]
        def choice(label, key):
            return Item(label, self.action(self.select_audio, key),
                        checked=lambda item: self.audio.preferred == key, radio=True)
        yield Item(text("Audio output"), Menu(
            Item(text("Output: ") + (self.audio.actual or text("No output device")), None, enabled=False),
            *(choice(label, key) for label, key in names)))
        def trigger_choice(label, mode):
            return Item(text(label), self.action(self.select_trigger, mode),
                        checked=lambda item: self.settings.trigger_mode == mode, radio=True)
        yield Item(text("Trigger"), Menu(
            trigger_choice("Left triple-click", "left_triple"),
            trigger_choice("Middle single-click", "middle_single")))
        yield Item(text("Preview sounds"), Menu(*(Item(text(n), self.action(self.play, n)) for n in ANSWERS)))
        yield Menu.SEPARATOR
        yield Item(text("Open configuration file"), self.action(self.open_configuration))
        yield Item(text("Quit"), self.quit)

    def update(self):
        if not self.menu_live or self.closed:
            return
        self.icon.schedule_menu_update()

    def set_status(self, value):
        if self.closed:
            return
        self.status = value
        self.gate.enable(value == "Ready" or value in RETRYABLE_STATUSES)
        self.update()

    async def open_configuration(self):
        await asyncio.to_thread(open_config, self.directory / "config.toml")

    async def select_audio(self, name):
        self.audio.select(name)
        await asyncio.to_thread(self.audio.refresh)
        self.update()

    async def select_trigger(self, mode):
        previous = self.settings.trigger_mode
        self.settings.trigger_mode = mode
        try:
            self.settings.save(self.directory)
        except Exception:
            self.settings.trigger_mode = previous
            raise
        self.gate.set_trigger_mode(mode)
        self.update()

    async def play(self, name):
        try:
            await asyncio.to_thread(self.audio.play, name)
        except Exception as exc:
            LOG.warning("Audio output unavailable: %s", type(exc).__name__)
        self.update()

    def runtime_download_progress(self, percent):
        if self.closed or self.runtime_cancel.is_set():
            return
        status = "Preparing Codex" if percent is None else "Downloading Codex"
        if status != self.status or percent != self.runtime_progress:
            self.runtime_progress = percent
            self.set_status(status)

    async def cancel_runtime(self):
        if self.runtime_task is None:
            return
        self.runtime_cancel.set()
        self.set_status("Cancelling download")

    async def download_runtime(self):
        # Only this explicit tray action may initiate a download.
        await self.recheck(download=True)

    async def ensure_runtime(self, download=False):
        if self.engine is not None:
            return True
        self.runtime_cancel.clear()
        self.runtime_error = None
        self.runtime_progress = None
        self.set_status("Downloading Codex" if download else "Checking Codex")
        try:
            if download:
                def progress(percent):
                    self.loop.call_soon_threadsafe(self.runtime_download_progress, percent)
                operation = asyncio.to_thread(runtime.download, self.directory, self.runtime_cancel, progress)
            else:
                saved = Settings.load(self.directory).codex_bin
                operation = asyncio.to_thread(runtime.discover, saved, self.runtime_cancel)
            self.runtime_task = asyncio.create_task(operation)
            path = await asyncio.shield(self.runtime_task)
            if self.closed:
                return False
            if self.runtime_cancel.is_set() or path is None:
                self.set_status("No compatible Codex found")
                return False
            # Preserve edits made through the configuration file during setup.
            settings = Settings.load(self.directory)
            settings.codex_bin = str(path)
            settings.save(self.directory)
            self.settings.codex_bin = str(path)
            self.engine = Engine(self.directory, self.settings)
            return True
        except asyncio.CancelledError:
            # Cancelling to_thread does not stop its worker. Drain it before another retry.
            self.runtime_cancel.set()
            if self.runtime_task:
                await asyncio.gather(self.runtime_task, return_exceptions=True)
            raise
        except runtime.DownloadCancelled:
            self.set_status("No compatible Codex found")
        except Exception as exc:
            if self.runtime_cancel.is_set():
                self.set_status("No compatible Codex found")
                return False
            LOG.exception("Codex preparation failed")
            self.runtime_error = ("Runtime verification failed" if isinstance(exc, ValueError)
                                  else "Check connection, disk space and runtime path")
            self.set_status("Codex preparation failed")
        finally:
            self.runtime_task = None
        return False

    async def recheck(self, startup=False, request=None, download=False):
        if (self.closed or self.check_task is not None or self.status in ("Working", "Waiting for sign-in")
                or (self.gate.current is not None and self.gate.current != request)):
            return
        self.check_task = asyncio.current_task()
        previous_status = self.status
        self.set_status("Starting")
        try:
            # Explicit downloads have no whole-file timeout; network reads are bounded.
            async with asyncio.timeout(None if download else 30):
                if not await self.ensure_input(request_permissions=request is None):
                    return
                new_engine = self.engine is None
                if not await self.ensure_runtime(download):
                    return
                startup = startup or new_engine
                await self.check_recovery(startup, previous_status, request)
        except TimeoutError:
            LOG.warning("Recovery check timed out")
            self.set_status("Codex preparation failed" if self.engine is None else "Connection unavailable")
        except Exception as exc:
            LOG.exception("Recovery check failed")
            self.set_status(error_status(exc))
        finally:
            self.check_task = None

    async def ensure_input(self, request_permissions):
        if not permissions(request=request_permissions, input_only=True):
            self.set_status(INPUT_ACCESS_REQUIRED)
            return False
        if self.listener is None or not self.listener.is_alive():
            self.listener = mouse.Listener(on_click=self.click, suppress=False)
            self.listener.start()
            await asyncio.to_thread(self.listener.wait)
        if self.closed:
            return False
        if not self.listener.is_alive():
            self.set_status(INPUT_ACCESS_REQUIRED)
            return False
        return True

    async def check_recovery(self, startup, previous_status, request):
        if not permissions(request=request is None):
            self.set_status(SCREEN_ACCESS_REQUIRED)
            return
        if not startup:
            await self.engine.client.close()
        if self.failed_operation:
            kind, operation = self.failed_operation
            if kind == "capture":
                await asyncio.to_thread(check_capture, request or operation, self.shots)
                self.failed_operation = None
            elif kind == "action" and request is None:
                function, args = operation
                await function(*args)
                self.failed_operation = None
        status = await self.engine.check_access(refresh_token=previous_status == "Sign-in required")
        if self.closed:
            return
        if status == "Ready" and self.failed_operation:
            # A successful account probe cannot validate an earlier model/unknown failure.
            status = ACCESS_UNVERIFIED
        self.set_status(status)

    async def sign_in(self):
        if self.login or self.status != "Sign-in required":
            return
        self.set_status("Waiting for sign-in")
        try:
            self.login = await self.engine.client.login_chatgpt()
            if not await asyncio.to_thread(webbrowser.open, self.login.auth_url):
                await self.login.cancel()
                self.set_status("Sign-in required")
                return
            result = await self.login.wait()
            if result.success:
                self.set_status("Starting")
                if self.request_task and not self.request_task.done():
                    await asyncio.shield(self.request_task)
                await self.recheck(startup=True)
            else:
                self.set_status("Sign-in required")
        finally:
            self.login = None

    async def cancel_login(self):
        if self.login:
            await self.login.cancel()

    def click(self, x, y, button, pressed, *extra):
        if button == mouse.Button.right:
            self.gate.set_right_pressed(pressed)
            return
        if pressed and button in (mouse.Button.left, mouse.Button.middle):
            request = self.gate.click(x, y, time.monotonic(), button=button.name)
            if request:
                self.loop.call_soon_threadsafe(self.start_question, request)

    def start_question(self, request):
        if not self.closed and self.gate.current == request:
            if self.status in RETRYABLE_STATUSES:
                task = self.retry_question(request)
            elif self.status != "Ready":
                self.gate.finish(request, None, time.monotonic())
                return
            elif request.capture_only:
                task = self.save_screenshot(request)
            else:
                task = self.question(request)
            self.request_task = self.loop.create_task(task)

    async def retry_question(self, request):
        try:
            # Recovery shares this trigger's deadline and claimed request slot.
            async with asyncio.timeout(max(0, request.deadline - time.monotonic())):
                await self.recheck(request=request)
        except TimeoutError:
            LOG.warning("Request %s recovery timed out", request.number)
            self.set_status("Codex preparation failed" if self.engine is None else "Connection unavailable")
        if self.closed or self.gate.current != request:
            return
        if self.status not in ("Ready", ACCESS_UNVERIFIED):
            await self.reject_question(request)
        elif request.capture_only:
            await self.save_screenshot(request, ready_status=self.status)
        else:
            await self.question(request)

    async def reject_question(self, request):
        self.pending_screenshots.clear()
        LOG.warning("Request %s rejected: %s", request.number, self.status)
        try:
            await self.play("FAIL")
        finally:
            self.gate.finish(request, "FAIL", time.monotonic())

    async def save_screenshot(self, request, ready_status="Ready"):
        self.set_status("Working")
        saved, path = False, None
        try:
            async with asyncio.timeout(max(0, request.deadline - time.monotonic())):
                path = await asyncio.to_thread(capture, request, self.shots)
                saved = True
        except TimeoutError:
            LOG.error("Capture %s timed out", request.number)
        except Exception:
            LOG.exception("Capture %s failed", request.number)
        # Boolean success is local bookkeeping; no new model/audio result is added.
        outcome = self.gate.finish(request, saved, time.monotonic())
        if outcome is None:
            return
        if outcome is True:
            self.pending_screenshots.append(path)
            LOG.info("Capture %s staged: %s", request.number, path)
        else:
            self.failed_operation = ("capture", request)
            self.pending_screenshots.clear()
            await self.play("FAIL")
        if not self.closed:
            self.set_status(ready_status if outcome is True else "Request failed")

    async def question(self, request):
        self.set_status("Working")
        result, next_status = "FAIL", "Ready"
        paths, self.pending_screenshots = self.pending_screenshots, []
        LOG.info("Request %s started", request.number)
        phase = "capture"
        try:
            async with asyncio.timeout(max(0, request.deadline - time.monotonic())):
                path = await asyncio.to_thread(capture, request, self.shots)
                paths.append(path)
                phase = "model"
                result = await self.engine.solve(paths)
                self.failed_operation = None
        except TimeoutError:
            LOG.error("Request %s timed out", request.number)
            self.failed_operation = (phase, request if phase == "capture" else None)
            next_status = "Request failed"
        except Exception as exc:
            next_status = error_status(exc)
            LOG.exception("Request %s failed", request.number)
            if phase == "capture" or next_status == "Request failed":
                self.failed_operation = (phase, request if phase == "capture" else None)
        result = self.gate.finish(request, result, time.monotonic())
        settings = getattr(self, "settings", None)
        if settings and not settings.retain_history and result in CHOICES:
            for path in paths:
                with suppress(OSError):
                    path.unlink()
        LOG.info("Request %s completed: %s screenshots=%s", request.number, result, paths)
        if result is not None:
            await self.play(result)
            if not self.closed:
                self.set_status(next_status)

    async def serve(self):
        async def refresh_audio():
            while not self.closed:
                before = (self.audio.outputs, self.audio.actual)
                try:
                    await asyncio.to_thread(self.audio.refresh)
                except Exception:
                    self.audio.outputs, self.audio.actual = {}, None
                if before != (self.audio.outputs, self.audio.actual):
                    self.update()
                await asyncio.sleep(4)
        discovery = asyncio.create_task(refresh_audio())
        startup = asyncio.create_task(self.recheck(startup=True))
        await self.stop_event.wait()
        discovery.cancel()
        self.runtime_cancel.set()
        if self.listener:
            self.listener.stop()
        if self.login:
            with suppress(Exception):
                await asyncio.wait_for(self.cancel_login(), 2)
        if self.request_task:
            self.request_task.cancel()
            await asyncio.gather(self.request_task, return_exceptions=True)
        if self.check_task:
            self.check_task.cancel()
            await asyncio.gather(self.check_task, return_exceptions=True)
        self.pending_screenshots.clear()
        await asyncio.gather(discovery, startup, return_exceptions=True)
        if self.engine:
            await self.engine.client.close()

    def work(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.serve())
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_default_executor())
            self.loop.close()

    def quit(self, icon=None, item=None):
        if not self.closed:
            self.gate.close()
            self.closed = True
            self.audio.closed.set()
            self.loop.call_soon_threadsafe(self.stop_event.set)
            self.icon.stop()

    def run(self):
        def setup(icon):
            icon.visible = True
            self.menu_live = True
            self.worker.start()
        try:
            self.icon.run(setup)
        finally:
            self.quit()
            if self.worker.ident:
                self.worker.join()


def main():
    directory = prepare_data_directory()
    lock = FileLock(directory / "instance.lock")
    try:
        with lock.acquire(timeout=0):
            logging.basicConfig(handlers=[RotatingFileHandler(directory / "quizchirp.log",
                maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")],
                level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")
            try:
                tray = Tray(directory)
                tray.run()
            except Exception:
                LOG.exception("Desktop startup failed")
                raise
    except Timeout:
        return


if __name__ == "__main__":
    main()
