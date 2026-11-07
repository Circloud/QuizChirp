import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from quizchirp.shortcuts import ensure_shortcuts
from quizchirp.i18n import Translator


@patch('quizchirp.shortcuts.subprocess.CREATE_NO_WINDOW', 0x08000000, create=True)
class Shortcuts(unittest.TestCase):
    def test_initial_language_and_create_once(self):
        for language in ('en', 'zh-CN'):
            with tempfile.TemporaryDirectory() as root, patch('quizchirp.shortcuts.sys.platform', 'win32'), patch('quizchirp.shortcuts.subprocess.run') as run:
                directory = Path(root)
                ensure_shortcuts(directory, language)
                self.assertEqual(run.call_args.args[0][-1], Translator(language)('QuizChirp'))
                self.assertTrue((directory / 'shortcuts.json').exists())
                ensure_shortcuts(directory, language)
                run.assert_called_once()

    def test_failure_can_retry(self):
        with tempfile.TemporaryDirectory() as root, patch('quizchirp.shortcuts.sys.platform', 'win32'), patch('quizchirp.shortcuts.subprocess.run', side_effect=OSError('test')) as run:
            with self.assertLogs('quizchirp.shortcuts', level='ERROR'):
                ensure_shortcuts(Path(root), 'en')
            self.assertFalse((Path(root) / 'shortcuts.json').exists())
