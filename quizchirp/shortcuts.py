"""Register the Windows portable executable in the current user's Start Menu."""
import logging
import os
from pathlib import Path
import subprocess
import sys


SHORTCUT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$programs = [Environment]::GetFolderPath('Programs')
if (!$programs) { throw 'Windows Start Menu folder is unavailable.' }
$executable = $env:QUIZCHIRP_SHORTCUT_EXECUTABLE
if (!(Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'QuizChirp executable is missing.'
}
$null = New-Item -ItemType Directory -Path $programs -Force
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $programs 'QuizChirp.lnk'))
$shortcut.TargetPath = $executable
$shortcut.WorkingDirectory = Split-Path -Parent $executable
$shortcut.Arguments = ''
$shortcut.IconLocation = "$executable,0"
$shortcut.Description = 'QuizChirp'
$shortcut.WindowStyle = 1
$shortcut.Save()
"""


def ensure_start_menu_shortcut():
    """Refresh the target after a move; failure must not prevent app startup."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SHORTCUT_SCRIPT],
            env={**os.environ, "QUIZCHIRP_SHORTCUT_EXECUTABLE": str(Path(sys.executable).resolve())},
            check=True, capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        logging.getLogger(__name__).exception("Could not update Start Menu shortcut; will retry next launch")
