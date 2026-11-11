import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from quizchirp.shortcuts import SHORTCUT_SCRIPT, ensure_start_menu_shortcut


class PortableShortcuts(unittest.TestCase):
    def test_source_and_non_windows_launches_do_not_create_shortcuts(self):
        for platform, frozen in (("win32", False), ("darwin", True), ("linux", True)):
            with self.subTest(platform=platform, frozen=frozen), \
                 patch("quizchirp.shortcuts.sys.platform", platform), \
                 patch("quizchirp.shortcuts.sys.frozen", frozen, create=True), \
                 patch("quizchirp.shortcuts.subprocess.run") as run:
                ensure_start_menu_shortcut()
                run.assert_not_called()

    def test_portable_launch_refreshes_executable_and_tolerates_failures(self):
        with patch("quizchirp.shortcuts.sys.platform", "win32"), \
             patch("quizchirp.shortcuts.sys.frozen", True, create=True), \
             patch("quizchirp.shortcuts.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True), \
             patch("quizchirp.shortcuts.subprocess.run") as run:
            for executable in ("original/QuizChirp.exe", "moved/QuizChirp.exe"):
                with patch("quizchirp.shortcuts.sys.executable", executable):
                    ensure_start_menu_shortcut()
                self.assertEqual(run.call_args.kwargs["env"]["QUIZCHIRP_SHORTCUT_EXECUTABLE"],
                                 str(Path(executable).resolve()))
            self.assertEqual(run.call_count, 2)
            for error in (OSError("denied"), subprocess.TimeoutExpired("powershell", 10),
                          subprocess.CalledProcessError(1, "powershell")):
                run.side_effect = error
                with self.assertLogs("quizchirp.shortcuts", level="ERROR"):
                    ensure_start_menu_shortcut()

    @unittest.skipUnless(sys.platform == "win32", "Windows shortcut integration")
    def test_windows_shortcut_creation_and_relocation(self):
        # Redirect only the known-folder lookup so real links stay inside the test folder.
        script = SHORTCUT_SCRIPT.replace(
            "[Environment]::GetFolderPath('Programs')", "$env:QUIZCHIRP_TEST_PROGRAMS")
        script += r"""
$saved = $shell.CreateShortcut((Join-Path $programs 'QuizChirp.lnk'))
if ($saved.TargetPath -ne $executable -or
    $saved.WorkingDirectory -ne (Split-Path -Parent $executable) -or
    $saved.Arguments -ne '' -or $saved.IconLocation -ne "$executable,0") {
    throw 'Shortcut verification failed.'
}
"""
        with tempfile.TemporaryDirectory() as root:
            programs = Path(root) / "Programs"
            for folder in ("original space's $folder", "moved space's $folder"):
                # Match the app's canonical path: Windows may expand 8.3 paths in links.
                executable = (Path(root) / folder / "QuizChirp.exe").resolve()
                executable.parent.mkdir()
                executable.touch()
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                    env={**os.environ, "QUIZCHIRP_SHORTCUT_EXECUTABLE": str(executable),
                         "QUIZCHIRP_TEST_PROGRAMS": str(programs)},
                    capture_output=True, text=True, errors="replace", timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([p.name for p in programs.iterdir()], ["QuizChirp.lnk"])
