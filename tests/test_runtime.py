import asyncio
import time
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from quizchirp.app import Tray, RETRYABLE_STATUSES, SCREEN_ACCESS_REQUIRED, INPUT_ACCESS_REQUIRED
from quizchirp.audio import Audio, VOICES
from quizchirp.core import Gate, Request
from quizchirp.config import Settings
from quizchirp.engine import ACCESS_UNVERIFIED


class Runtime(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Exercise the event handlers without registering an OS hook or tray icon.
        self.tray = Tray.__new__(Tray)
        self.tray.gate = Gate(0.5, (4, 4))
        self.tray.closed = False
        self.tray.menu_live = False
        self.tray.status = "Starting"
        self.tray.listener = Mock()
        self.tray.shots = Path(".")
        self.tray.play = AsyncMock()
        self.tray.engine = SimpleNamespace(client=AsyncMock(), solve=AsyncMock(),
                                           check_access=AsyncMock(return_value="Ready"))
        self.tray.check_task = None
        self.tray.request_task = None
        self.tray.failed_operation = None
        self.tray.login = None
        self.tray.pending_screenshots = []

    def claim(self, capture_only=False):
        self.tray.gate.serial += 1
        request = Request(self.tray.gate.serial, 0, 0,
                          time.monotonic() + self.tray.gate.timeout, capture_only)
        self.tray.gate.current = request
        return request

    async def test_mouse_chord_stages_silently_then_submits_in_order(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.set_status("Ready")
        self.tray.engine.solve.return_value = "C"
        paths = [Path(f"page-{n}.png") for n in range(4)]
        with patch("quizchirp.app.capture", side_effect=paths) as capture:
            for index in range(3):
                # Model a fresh click burst without waiting for real wall time.
                self.tray.gate.last = float("-inf")
                self.tray.click(0, 0, mouse.Button.right, index < 2)
                for _ in range(4):
                    self.tray.click(0, 0, mouse.Button.left, True)
                await asyncio.sleep(0)
                await self.tray.request_task
                if index < 2:
                    self.tray.engine.solve.assert_not_awaited()
                    self.tray.play.assert_not_awaited()
                    self.assertEqual(self.tray.pending_screenshots, paths[:index + 1])
            self.assertEqual(capture.call_count, 3)
            self.tray.engine.solve.assert_awaited_once_with(paths[:3])
            self.tray.play.assert_awaited_once_with("C")
            self.assertEqual(self.tray.pending_screenshots, [])
            await self.tray.question(self.claim())
            self.tray.engine.solve.assert_awaited_with([paths[3]])

    async def test_failed_save_clears_collection_and_uses_existing_fail_sound(self):
        self.tray.pending_screenshots = [Path("previous.png")]
        with patch("quizchirp.app.capture", side_effect=OSError("Capture failed")):
            await self.tray.save_screenshot(self.claim(capture_only=True))
        self.assertEqual(self.tray.pending_screenshots, [])
        self.tray.engine.solve.assert_not_awaited()
        self.tray.play.assert_awaited_once_with("FAIL")
        self.assertIsNone(self.tray.gate.current)
        self.assertEqual(self.tray.status, "Request failed")

    async def test_right_middle_stages_then_unmodified_middle_submits(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.gate.set_trigger_mode("middle_single")
        self.tray.set_status("Ready")
        self.tray.engine.solve.return_value = "D"
        paths = [Path("first.png"), Path("last.png")]
        with patch("quizchirp.app.capture", side_effect=paths):
            self.tray.click(0, 0, mouse.Button.right, True)
            self.tray.click(0, 0, mouse.Button.middle, True)
            # Releasing right before the worker runs must not change the action.
            self.tray.click(0, 0, mouse.Button.right, False)
            await asyncio.sleep(0)
            await self.tray.request_task
            self.tray.engine.solve.assert_not_awaited()
            self.tray.play.assert_not_awaited()
            self.assertEqual(self.tray.pending_screenshots, paths[:1])
            self.tray.click(0, 0, mouse.Button.middle, True)
            await asyncio.sleep(0)
            await self.tray.request_task
        self.tray.engine.solve.assert_awaited_once_with(paths)
        self.tray.play.assert_awaited_once_with("D")
        self.assertEqual(self.tray.pending_screenshots, [])

    async def test_expired_save_does_not_stage_or_send(self):
        request = Request(1, 0, 0, time.monotonic() - 1, True)
        self.tray.gate.current = request
        with patch("quizchirp.app.capture", return_value=Path("late.png")):
            await self.tray.save_screenshot(request)
        self.assertEqual(self.tray.pending_screenshots, [])
        self.tray.engine.solve.assert_not_awaited()
        self.tray.play.assert_awaited_once_with("FAIL")

    async def test_closed_request_cannot_stage_or_play(self):
        request = self.claim(capture_only=True)
        def capture(*args):
            self.tray.gate.close()
            self.tray.closed = True
            return Path("closed.png")
        with patch("quizchirp.app.capture", side_effect=capture):
            await self.tray.save_screenshot(request)
        self.assertEqual(self.tray.pending_screenshots, [])
        self.tray.play.assert_not_awaited()

    async def test_retention_applies_to_the_whole_submitted_group(self):
        for level, answer in (("WARNING", "B"), ("WARNING", "E"), ("WARNING", "F"),
                              ("WARNING", "FAIL"), ("INFO", "B"), ("INFO", "F")):
            with self.subTest(level=level, answer=answer), tempfile.TemporaryDirectory() as folder:
                paths = [Path(folder) / f"page-{n}.png" for n in range(3)]
                for path in paths:
                    path.write_bytes(b"test")
                self.tray.settings = Settings(log_level=level)
                self.tray.pending_screenshots = paths[:2]
                self.tray.engine.solve.return_value = answer
                self.tray.play.reset_mock()
                with patch("quizchirp.app.capture", return_value=paths[-1]):
                    await self.tray.question(self.claim())
                self.assertEqual(self.tray.pending_screenshots, [])
                self.tray.play.assert_awaited_once_with(answer)
                self.assertEqual([path.exists() for path in paths],
                                 [level == "INFO" or answer == "FAIL"] * 3)

    async def test_login_notification_enables_input(self):
        client = self.tray.engine.client
        self.tray.engine.check_access.side_effect = ["Sign-in required", "Ready"]
        handle = SimpleNamespace(auth_url="https://example.invalid",
                                 wait=AsyncMock(return_value=SimpleNamespace(success=True)))
        client.login_chatgpt.return_value = handle
        with patch("quizchirp.app.permissions", return_value=True):
            await self.tray.recheck(startup=True)
            self.assertEqual(self.tray.status, "Sign-in required")
            with patch("quizchirp.app.webbrowser.open", return_value=True):
                await self.tray.sign_in()
        self.assertTrue(self.tray.gate.ready)
        handle.wait.assert_awaited_once()

    async def test_signed_out_burst_plays_fail_without_capture(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.set_status("Sign-in required")
        self.tray.engine.check_access.return_value = "Sign-in required"
        with patch("quizchirp.app.capture") as capture:
            for _ in range(4):
                self.tray.click(0, 0, mouse.Button.left, True)
            await asyncio.sleep(0)
            await self.tray.request_task
        self.tray.play.assert_awaited_once_with("FAIL")
        capture.assert_not_called()
        self.tray.engine.solve.assert_not_awaited()
        self.assertEqual(self.tray.status, "Sign-in required")
        self.assertIsNone(self.tray.gate.current)

    async def test_network_error_finishes_once_and_next_trigger_recovers(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.pending_screenshots = [Path("saved.png")]
        self.tray.gate.enable(True)
        start = time.monotonic()
        for n in range(3):
            req = self.tray.gate.click(0, 0, start+n*0.01)
        self.tray.engine.solve.side_effect = ConnectionError("Connection unavailable")
        with patch("quizchirp.app.capture", return_value=Path("practice.png")):
            await self.tray.question(req)
        self.tray.play.assert_awaited_once_with("FAIL")
        self.assertEqual(self.tray.status, "Connection unavailable")
        self.assertIsNone(self.tray.gate.current)
        self.assertEqual(self.tray.pending_screenshots, [])
        self.tray.engine.solve.assert_awaited_once_with([Path("saved.png"), Path("practice.png")])
        self.tray.engine.solve.side_effect = None
        self.tray.engine.solve.return_value = "B"
        self.tray.engine.check_access.return_value = "Ready"
        self.tray.gate.last = float("-inf")
        with patch("quizchirp.app.permissions", return_value=True), \
             patch("quizchirp.app.capture", return_value=Path("next.png")):
            for _ in range(4):
                self.tray.click(0, 0, mouse.Button.left, True)
            await asyncio.sleep(0)
            await self.tray.request_task
        self.tray.engine.client.close.assert_awaited_once()
        self.tray.engine.solve.assert_awaited_with([Path("next.png")])
        self.assertEqual(self.tray.engine.solve.await_count, 2)
        self.assertEqual([call.args[0] for call in self.tray.play.await_args_list], ["FAIL", "B"])
        self.assertEqual(self.tray.status, "Ready")

    async def test_retryable_states_preserve_staging_intent_and_offer_retry_menu(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.gate.set_trigger_mode("middle_single")
        self.tray.settings = Settings()
        self.tray.text = lambda value: value
        self.tray.audio = SimpleNamespace(outputs={}, actual=None, preferred=None)
        self.tray.engine.check_access.return_value = "Ready"
        for status in RETRYABLE_STATUSES:
            with self.subTest(status=status), patch("quizchirp.app.permissions", return_value=True), \
                 patch("quizchirp.app.capture", return_value=Path("staged.png")) as capture:
                self.tray.pending_screenshots = []
                self.tray.set_status(status)
                self.assertIn("Retry", [item.text for item in self.tray.items()])
                self.tray.click(0, 0, mouse.Button.right, True)
                self.tray.click(0, 0, mouse.Button.middle, True)
                self.tray.click(0, 0, mouse.Button.right, False)
                await asyncio.sleep(0)
                await self.tray.request_task
                capture.assert_called_once()
                self.assertEqual(self.tray.pending_screenshots, [Path("staged.png")])
                self.assertEqual(self.tray.status, "Ready")
        self.tray.engine.solve.assert_not_awaited()
        self.tray.play.assert_not_awaited()

    async def test_repeated_usage_limit_then_success_needs_only_one_trigger_each(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.gate.set_trigger_mode("middle_single")
        self.tray.set_status("Usage limit reached")
        self.tray.engine.check_access.return_value = "Ready"
        self.tray.engine.check_access.side_effect = ["Usage limit reached", "Ready"]
        self.tray.engine.solve.return_value = "C"
        with patch("quizchirp.app.permissions", return_value=True), \
             patch("quizchirp.app.capture", return_value=Path("current.png")):
            for expected in ("Usage limit reached", "Ready"):
                self.tray.click(0, 0, mouse.Button.middle, True)
                await asyncio.sleep(0)
                await self.tray.request_task
                self.assertEqual(self.tray.status, expected)
                self.assertIsNone(self.tray.gate.current)
        self.assertEqual([call.args[0] for call in self.tray.play.await_args_list], ["FAIL", "C"])
        self.assertEqual(self.tray.engine.solve.await_count, 1)

    async def test_failed_recovery_clears_group_without_capture_or_duplicate_feedback(self):
        from pynput import mouse
        async def stalled_account(**kwargs):
            await asyncio.Event().wait()
        self.tray.loop = asyncio.get_running_loop()
        self.tray.gate.set_trigger_mode("middle_single")
        self.tray.gate.timeout = 0.05
        for account, expected in (
            (AsyncMock(side_effect=ConnectionError("connection unavailable")), "Connection unavailable"),
            (AsyncMock(return_value="Sign-in required"), "Sign-in required"),
            (AsyncMock(side_effect=stalled_account), "Connection unavailable"),
        ):
            with self.subTest(expected=expected), patch("quizchirp.app.permissions", return_value=True), \
                 patch("quizchirp.app.capture") as capture:
                self.tray.engine.check_access = account
                self.tray.pending_screenshots = [Path("saved.png")]
                self.tray.play.reset_mock()
                self.tray.set_status("Usage limit reached")
                self.tray.click(0, 0, mouse.Button.middle, True)
                self.tray.click(0, 0, mouse.Button.middle, True)
                await asyncio.sleep(0)
                await self.tray.request_task
                self.assertEqual(self.tray.status, expected)
                self.assertIsNone(self.tray.gate.current)
                self.assertEqual(self.tray.pending_screenshots, [])
                self.tray.play.assert_awaited_once_with("FAIL")
                capture.assert_not_called()
        self.tray.engine.solve.assert_not_awaited()

    async def test_screen_permission_recovery_keeps_input_listener(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.listener = None
        self.tray.gate.set_trigger_mode("middle_single")
        self.tray.engine.check_access.return_value = "Ready"
        self.tray.engine.solve.return_value = "A"
        with patch("quizchirp.app.permissions", side_effect=[True, False, True, True]), \
             patch("quizchirp.app.mouse.Listener") as listener, \
             patch("quizchirp.app.capture", return_value=Path("current.png")):
            listener.return_value.is_alive.return_value = True
            await self.tray.recheck(startup=True)
            self.assertEqual(self.tray.status, SCREEN_ACCESS_REQUIRED)
            self.tray.click(0, 0, mouse.Button.middle, True)
            await asyncio.sleep(0)
            await self.tray.request_task
        listener.assert_called_once()
        self.assertEqual(self.tray.status, "Ready")
        self.tray.play.assert_awaited_once_with("A")

    async def test_input_permission_can_be_rechecked_without_mouse_input(self):
        self.tray.listener = None
        with patch("quizchirp.app.permissions", return_value=False), patch("quizchirp.app.mouse.Listener") as listener:
            await self.tray.recheck(startup=True)
        listener.assert_not_called()
        self.assertEqual(self.tray.status, INPUT_ACCESS_REQUIRED)
        self.assertFalse(self.tray.gate.ready)
        with patch("quizchirp.app.permissions", return_value=True), patch("quizchirp.app.mouse.Listener") as listener:
            listener.return_value.is_alive.return_value = True
            await self.tray.recheck()
        listener.assert_called_once()
        self.assertEqual(self.tray.status, "Ready")
        self.assertTrue(self.tray.gate.ready)

    async def test_recovery_ignores_extra_input_and_shutdown_cancels_it(self):
        from pynput import mouse
        entered = asyncio.Event()
        async def account(**kwargs):
            entered.set()
            await asyncio.Event().wait()
        self.tray.loop = asyncio.get_running_loop()
        self.tray.gate.set_trigger_mode("middle_single")
        self.tray.set_status("Connection unavailable")
        self.tray.engine.check_access.side_effect = account
        with patch("quizchirp.app.permissions", return_value=True), patch("quizchirp.app.capture") as capture:
            self.tray.click(0, 0, mouse.Button.middle, True)
            await asyncio.wait_for(entered.wait(), 1)
            request_task = self.tray.request_task
            failed_action = Future()
            failed_action.set_exception(OSError("Cannot open configuration"))
            self.tray.action_done(failed_action)
            self.assertEqual(self.tray.status, "Starting")
            self.tray.click(0, 0, mouse.Button.middle, True)
            await asyncio.sleep(0)
            self.assertIs(self.tray.request_task, request_task)
            self.tray.gate.close()
            self.tray.closed = True
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        self.tray.engine.check_access.assert_awaited_once()
        capture.assert_not_called()
        self.tray.play.assert_not_awaited()

    async def test_timeout_cancels_active_solver(self):
        self.tray.pending_screenshots = [Path("saved.png")]
        self.tray.gate.timeout = 0.05
        self.tray.gate.enable(True)
        for _ in range(3):
            req = self.tray.gate.click(0, 0, time.monotonic())
        stopped = asyncio.Event()
        async def solve(path):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        self.tray.engine.solve = solve
        with patch("quizchirp.app.capture", return_value=Path("practice.png")):
            await self.tray.question(req)
        self.assertTrue(stopped.is_set())
        self.tray.play.assert_awaited_once_with("FAIL")
        self.assertTrue(self.tray.gate.ready)
        self.assertEqual(self.tray.pending_screenshots, [])

    async def test_manual_retry_only_checks_and_preserves_pending_images(self):
        self.tray.pending_screenshots = [Path("saved.png")]
        with patch("quizchirp.app.permissions", return_value=True), patch("quizchirp.app.capture") as capture:
            for result in ("Usage limit reached", ACCESS_UNVERIFIED, "Ready"):
                with self.subTest(result=result):
                    self.tray.set_status("Usage limit reached")
                    self.tray.engine.check_access.return_value = result
                    await self.tray.recheck()
                    self.assertEqual(self.tray.status, result)
                    self.assertEqual(self.tray.pending_screenshots, [Path("saved.png")])
                    self.assertIsNone(self.tray.gate.current)
        capture.assert_not_called()
        self.tray.engine.solve.assert_not_awaited()
        self.tray.play.assert_not_awaited()

    async def test_retry_verifies_failed_capture_and_retries_failed_setting(self):
        request = Request(1, 50, 60, time.monotonic() + 30)
        self.tray.failed_operation = ("capture", request)
        self.tray.set_status("Request failed")
        with patch("quizchirp.app.permissions", return_value=True), \
             patch("quizchirp.app.check_capture", side_effect=[OSError("Capture failed"), None]) as probe:
            await self.tray.recheck()
            self.assertEqual(self.tray.status, "Request failed")
            self.tray.engine.check_access.assert_not_awaited()
            await self.tray.recheck()
        probe.assert_called_with(request, self.tray.shots)
        self.assertEqual(self.tray.status, "Ready")
        self.assertIsNone(self.tray.failed_operation)

        self.tray.settings = Settings()
        self.tray.directory = Path("unused")
        with patch.object(self.tray.settings, "save", side_effect=[OSError("Cannot write settings"), None]), \
             patch("quizchirp.app.permissions", return_value=True):
            failed = Future()
            try:
                await self.tray.select_trigger("middle_single")
            except OSError as exc:
                failed.set_exception(exc)
            self.tray.action_done(failed, self.tray.select_trigger, ("middle_single",))
            self.assertEqual(self.tray.status, "Request failed")
            self.assertEqual(self.tray.settings.trigger_mode, "left_triple")
            await self.tray.recheck()
        self.assertEqual(self.tray.status, "Ready")
        self.assertEqual(self.tray.gate.trigger_mode, "middle_single")
        self.assertIsNone(self.tray.failed_operation)
        self.tray.engine.solve.assert_not_awaited()
        from quizchirp.desktop import check_capture
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "probe.png"
            image.write_bytes(b"probe")
            with patch("quizchirp.desktop.capture", return_value=image):
                check_capture(request, Path(folder))
            self.assertFalse(image.exists())

    async def test_model_failure_needs_real_submission_to_confirm_recovery(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.gate.set_trigger_mode("middle_single")
        self.tray.failed_operation = ("model", None)
        self.tray.set_status("Request failed")
        self.tray.engine.solve.return_value = "C"
        with patch("quizchirp.app.permissions", return_value=True), \
             patch("quizchirp.app.capture", side_effect=[Path("saved.png"), Path("current.png")]):
            await self.tray.recheck()
            self.assertEqual(self.tray.status, ACCESS_UNVERIFIED)
            self.tray.click(0, 0, mouse.Button.right, True)
            self.tray.click(0, 0, mouse.Button.middle, True)
            await asyncio.sleep(0)
            await self.tray.request_task
            self.assertEqual(self.tray.status, ACCESS_UNVERIFIED)
            self.tray.engine.solve.assert_not_awaited()
            self.tray.click(0, 0, mouse.Button.right, False)
            self.tray.click(0, 0, mouse.Button.middle, True)
            await asyncio.sleep(0)
            await self.tray.request_task
        self.assertEqual(self.tray.status, "Ready")
        self.assertIsNone(self.tray.failed_operation)
        self.tray.engine.solve.assert_awaited_once_with([Path("saved.png"), Path("current.png")])
        self.tray.play.assert_awaited_once_with("C")

    async def test_manual_retry_does_not_overlap_requests_or_other_checks(self):
        from pynput import mouse
        self.tray.loop = asyncio.get_running_loop()
        self.tray.gate.set_trigger_mode("middle_single")
        self.tray.set_status("Connection unavailable")
        request = self.claim()
        await self.tray.recheck()
        self.tray.engine.client.close.assert_not_awaited()
        self.tray.gate.finish(request, "FAIL", time.monotonic())
        entered, release = asyncio.Event(), asyncio.Event()
        async def check(**kwargs):
            entered.set()
            await release.wait()
            return "Ready"
        self.tray.engine.check_access.side_effect = check
        with patch("quizchirp.app.permissions", return_value=True):
            checking = asyncio.create_task(self.tray.recheck())
            await asyncio.wait_for(entered.wait(), 1)
            await self.tray.recheck()
            self.tray.click(0, 0, mouse.Button.middle, True)
            self.assertIsNone(self.tray.gate.current)
            release.set()
            await checking
        self.tray.engine.check_access.assert_awaited_once()
        self.assertEqual(self.tray.status, "Ready")
        self.assertIsNone(self.tray.check_task)


class Routing(unittest.TestCase):
    @patch("quizchirp.audio.random.triangular", return_value=0.0)
    def test_voice_rotation_uses_each_recording_without_adjacent_repeats(self, variation):
        audio = Audio(Path("unused-test-settings"))
        self.assertEqual(len(VOICES), 50)
        previous = None
        for _ in range(2):
            voices = set()
            for _ in VOICES:
                _, note = audio._cue("A")
                self.assertNotEqual(previous, note)
                voices.add(note)
                previous = note
            self.assertEqual(len(voices), len(VOICES))

    def test_preferred_disappears_and_returns(self):
        audio = Audio(Path("unused-test-settings"))
        audio.preferred = "Headphones"
        audio.default = "Speakers"
        audio.outputs = {"Speakers": 0, "Monitor": 1}
        self.assertEqual(list(audio._routes()), ["Speakers", "Monitor"])
        audio.outputs["Headphones"] = 2
        self.assertEqual(next(iter(audio._routes())), "Headphones")
        audio.default = None
        del audio.outputs["Headphones"]
        self.assertEqual(next(iter(audio._routes())), "Speakers")
        audio.outputs = {}
        self.assertEqual(list(audio._routes()), [])
