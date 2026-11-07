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
    async def test_missing_runtime_manual_path_and_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            tray = Tray.__new__(Tray)
            tray.directory = Path(folder)
            tray.settings = Settings.load(tray.directory)
            tray.engine = None
            tray.runtime_task = None
            tray.runtime_cancel = threading.Event()
            tray.closed = False
            tray.gate = Gate(.5, (4, 4))
            tray.update = Mock()
            tray.recheck = AsyncMock()
            tray.loop = asyncio.get_running_loop()
            with patch.object(runtime, 'discover', return_value=None), patch.object(runtime, 'download') as download:
                await tray.prepare_runtime()
                self.assertEqual(tray.status, 'No compatible Codex found')
                self.assertFalse(tray.gate.ready)
                download.assert_not_called()
            settings = Settings.load(tray.directory)
            settings.codex_bin = 'chosen'
            settings.save(tray.directory)
            with patch.object(runtime, 'discover', return_value=Path('valid').resolve()) as discover, \
                 patch('quizchirp.app.Engine') as engine:
                await tray.prepare_runtime()
                self.assertEqual(discover.call_args.args[0], 'chosen')
                self.assertEqual(tray.engine, engine.return_value)
                tray.recheck.assert_awaited_once_with(startup=True)

    async def test_cancel_prevents_second_download_and_engine_start(self):
        with tempfile.TemporaryDirectory() as folder:
            tray = Tray.__new__(Tray)
            tray.directory = Path(folder)
            tray.engine = None
            tray.runtime_task = None
            tray.runtime_cancel = threading.Event()
            tray.closed = False
            tray.gate = Gate(.5, (4, 4))
            tray.update = Mock()
            tray.loop = asyncio.get_running_loop()
            entered = asyncio.Event()
            def download(directory, cancelled, progress):
                tray.loop.call_soon_threadsafe(entered.set)
                if not cancelled.wait(3):
                    raise AssertionError('Cancellation was not delivered')
                raise runtime.DownloadCancelled()
            with patch.object(runtime, 'download', side_effect=download) as fetch:
                task = asyncio.create_task(tray.prepare_runtime(True))
                await asyncio.wait_for(entered.wait(), 3)
                await tray.prepare_runtime(True)
                await tray.cancel_runtime()
                await task
                fetch.assert_called_once()
                self.assertIsNone(tray.engine)
                self.assertEqual(tray.status, 'No compatible Codex found')
                self.assertIsNone(tray.runtime_task)


if __name__ == '__main__':
    unittest.main()
