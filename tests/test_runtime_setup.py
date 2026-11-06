import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quizchirp import runtime
from quizchirp.config import Settings
from quizchirp.i18n import Translator


class RuntimeSetup(unittest.TestCase):
    def test_saved_path_is_first(self):
        self.assertEqual(next(runtime.candidates("chosen")), Path("chosen"))

    def test_invalid_saved_path_falls_back_and_saves(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            Settings(codex_bin="missing").save(directory)
            with patch.object(runtime, "prepare_data_directory", return_value=directory), \
                 patch.object(runtime, "candidates", return_value=[Path("missing"), Path("valid")]), \
                 patch.object(runtime, "check", side_effect=[False, True]), \
                 patch("builtins.input", side_effect=AssertionError("must not prompt")):
                self.assertEqual(runtime.main(), 0)
            self.assertEqual(Settings.load(directory).codex_bin, str(Path("valid").resolve()))

    def test_download_failure_then_manual_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch.object(runtime, "prepare_data_directory", return_value=directory), \
                 patch.object(runtime, "candidates", return_value=[]), \
                 patch.object(runtime, "download", side_effect=OSError()), \
                 patch.object(runtime, "check", return_value=True), \
                 patch("builtins.input", side_effect=["1", "2", '"chosen path"']):
                self.assertEqual(runtime.main(), 0)
            self.assertEqual(Settings.load(directory).codex_bin, str(Path("chosen path").resolve()))

    def test_download_is_pinned_and_separate(self):
        with patch.object(runtime.subprocess, "run") as run:
            runtime.download()
        args = run.call_args.args[0]
        self.assertIn("--no-cache", args)
        self.assertIn(str(runtime.APP_ROOT / ".runtime"), args)
        self.assertIn("openai-codex-cli-bin==" + runtime.version("openai-codex"), args)

    def test_chinese_platform_prompt(self):
        text = Translator("zh-CN")("2. Enter the path to {exe}")
        self.assertIn("路径", text)
        self.assertNotIn(".exe", text.format(exe="codex"))


if __name__ == "__main__":
    unittest.main()
