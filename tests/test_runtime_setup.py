import asyncio
import hashlib
import io
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from quizchirp import runtime
from quizchirp.app import Tray
from quizchirp.config import Settings
from quizchirp.core import Gate


class RuntimeDownload(unittest.TestCase):
    def test_discovery_falls_back_without_downloading(self):
        with patch.object(runtime, 'candidates', return_value=[Path('missing'), Path('valid')]), \
             patch.object(runtime, 'check', side_effect=[False, True]), patch.object(runtime, 'download') as download:
            self.assertEqual(runtime.discover('missing', threading.Event()), Path('valid').resolve())
            download.assert_not_called()

    def test_verified_download_cancel_and_corruption_leave_no_partial_install(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as wheel:
            wheel.writestr('codex_cli_bin/bin/' + runtime.executable_name(), b'executable')
            wheel.writestr('codex_cli_bin/bin/helper', b'helper')
        payload = content.getvalue()
        spec = dict(url='https://example.invalid/runtime.whl', size=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest())
        for outcome in ('success', 'corrupt', 'cancel', 'incompatible'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                cancelled = threading.Event()
                def progress(percent):
                    if outcome == 'cancel':
                        cancelled.set()
                entry = {**spec, 'sha256': '0' * 64} if outcome == 'corrupt' else spec
                with patch.object(runtime, 'download_spec', return_value=entry), \
                     patch.object(runtime, 'urlopen', return_value=io.BytesIO(payload)), \
                     patch.object(runtime, 'check', return_value=outcome != 'incompatible') as check:
                    if outcome == 'success':
                        binary = runtime.download(directory, cancelled, progress)
                        self.assertEqual(binary.read_bytes(), b'executable')
                        self.assertEqual(binary.with_name('helper').read_bytes(), b'helper')
                    else:
                        with self.assertRaises((ValueError, RuntimeError, runtime.DownloadCancelled)):
                            runtime.download(directory, cancelled, progress)
                        self.assertEqual(list((directory / 'runtime').iterdir()), [])
                        if outcome in ('corrupt', 'cancel'):
                            check.assert_not_called()


class TrayRuntimeSetup(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.tray = tray = Tray.__new__(Tray)
        tray.directory = Path(self.folder.name)
        tray.settings = Settings.load(tray.directory)
        tray.engine = None
        tray.listener = None
        tray.runtime_task = tray.check_task = tray.request_task = None
        tray.runtime_cancel = threading.Event()
        tray.closed = False
        tray.status = "Starting"
        tray.gate = Gate(.5, (4, 4), trigger_mode="middle_single")
        tray.update = Mock()
        tray.play = AsyncMock()
        tray.failed_operation = None
        tray.pending_screenshots = []
        tray.shots = tray.directory

    async def test_startup_listens_before_runtime_and_manual_retry_reads_path(self):
        tray = self.tray
        tray.loop = asyncio.get_running_loop()
        with patch('quizchirp.app.permissions', return_value=True), \
             patch('quizchirp.app.mouse.Listener') as listener, \
             patch.object(runtime, 'discover', return_value=None), patch.object(runtime, 'download') as download:
            listener.return_value.is_alive.return_value = True
            await tray.recheck(startup=True)
            listener.return_value.start.assert_called_once()
            self.assertEqual(tray.status, 'No compatible Codex found')
            self.assertTrue(tray.gate.ready)
            download.assert_not_called()
        settings = Settings.load(tray.directory)
        settings.codex_bin = 'chosen'
        settings.save(tray.directory)
        with patch.object(runtime, 'discover', return_value=Path('valid').resolve()) as discover, \
             patch('quizchirp.app.Engine') as engine, \
             patch('quizchirp.app.permissions', return_value=True):
            engine.return_value.check_access = AsyncMock(return_value='Ready')
            await tray.recheck()
            self.assertEqual(discover.call_args.args[0], 'chosen')
            self.assertEqual(tray.status, 'Ready')
            tray.play.assert_not_awaited()

    async def test_trigger_recovers_runtime_then_continues_or_fails_without_active_setup(self):
        from pynput import mouse
        tray = self.tray
        tray.loop = asyncio.get_running_loop()
        for found, account, stage in ((None, None, False), (OSError('unavailable'), None, False),
                                      (Path('valid'), 'Sign-in required', False),
                                      (Path('valid'), 'Ready', False), (Path('valid'), 'Ready', True)):
            with self.subTest(found=found, account=account, stage=stage), \
                 patch('quizchirp.app.permissions', return_value=True) as permissions, \
                 patch('quizchirp.app.mouse.Listener') as listener, \
                 patch.object(runtime, 'discover', side_effect=[found]) as discover, \
                 patch.object(runtime, 'download') as download, \
                 patch('quizchirp.app.webbrowser.open') as browser, \
                 patch('quizchirp.app.Engine') as engine, \
                 patch('quizchirp.app.capture', return_value=Path('current.png')) as capture:
                listener.return_value.is_alive.return_value = True
                engine.return_value.check_access = AsyncMock(return_value=account)
                engine.return_value.solve = AsyncMock(return_value='A')
                tray.engine = None
                tray.play.reset_mock()
                tray.pending_screenshots = [Path('saved.png')]
                tray.set_status('Codex preparation failed')
                tray.click(0, 0, mouse.Button.right, stage)
                tray.click(0, 0, mouse.Button.middle, True)
                tray.click(0, 0, mouse.Button.middle, True)
                await asyncio.sleep(0)
                await tray.request_task
                discover.assert_called_once()
                download.assert_not_called()
                browser.assert_not_called()
                engine.return_value.client.login_chatgpt.assert_not_called()
                self.assertTrue(all(c.kwargs['request'] is False for c in permissions.call_args_list))
                self.assertIsNone(tray.gate.current)
                if account == 'Ready':
                    capture.assert_called_once()
                    if stage:
                        tray.play.assert_not_awaited()
                        engine.return_value.solve.assert_not_awaited()
                        self.assertEqual(tray.pending_screenshots, [Path('saved.png'), Path('current.png')])
                    else:
                        tray.play.assert_awaited_once_with('A')
                        engine.return_value.solve.assert_awaited_once_with([Path('saved.png'), Path('current.png')])
                else:
                    capture.assert_not_called()
                    tray.play.assert_awaited_once_with('FAIL')

    async def test_cancel_prevents_second_download_and_engine_start(self):
        tray = self.tray
        tray.loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        def download(directory, cancelled, progress):
            tray.loop.call_soon_threadsafe(entered.set)
            if not cancelled.wait(3):
                raise AssertionError('Cancellation was not delivered')
            raise runtime.DownloadCancelled()
        with patch.object(runtime, 'download', side_effect=download) as fetch, \
             patch.object(tray, 'ensure_input', AsyncMock(return_value=True)):
            task = asyncio.create_task(tray.download_runtime())
            await asyncio.wait_for(entered.wait(), 3)
            await tray.download_runtime()
            await tray.cancel_runtime()
            await task
            fetch.assert_called_once()
            self.assertIsNone(tray.engine)
            self.assertEqual(tray.status, 'No compatible Codex found')
            self.assertIsNone(tray.runtime_task)

    async def test_trigger_timeout_stops_runtime_worker_before_next_retry(self):
        from pynput import mouse
        tray = self.tray
        tray.loop = asyncio.get_running_loop()
        tray.gate.timeout = .05
        stopped = threading.Event()
        def discover(saved, cancelled):
            if not cancelled.wait(3):
                raise AssertionError('Runtime worker was not cancelled')
            stopped.set()
        with patch.object(runtime, 'discover', side_effect=discover), \
             patch.object(tray, 'ensure_input', AsyncMock(return_value=True)), \
             patch('quizchirp.app.capture') as capture:
            tray.set_status('No compatible Codex found')
            tray.click(0, 0, mouse.Button.middle, True)
            await asyncio.sleep(0)
            await tray.request_task
            self.assertTrue(stopped.is_set())
            self.assertIsNone(tray.runtime_task)
            self.assertIsNone(tray.check_task)
            self.assertIsNone(tray.gate.current)
            self.assertEqual(tray.status, 'Codex preparation failed')
            tray.play.assert_awaited_once_with('FAIL')
            capture.assert_not_called()

    async def test_in_progress_states_ignore_triggers_including_login(self):
        from pynput import mouse
        tray = self.tray
        tray.loop = asyncio.get_running_loop()
        for status in ('Starting', 'Checking Codex', 'Downloading Codex', 'Preparing Codex',
                       'Cancelling download', 'Waiting for sign-in', 'Working'):
            tray.set_status(status)
            tray.click(0, 0, mouse.Button.middle, True)
            await asyncio.sleep(0)
            self.assertIsNone(tray.request_task)
            self.assertIsNone(tray.gate.current)
        tray.play.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
