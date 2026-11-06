import json
import logging
import subprocess
import sys

from .i18n import Translator
from .paths import APP_ROOT


def ensure_shortcuts(directory, language):
    """Create current-user Windows shortcuts once per portable installation."""
    if sys.platform != "win32":
        return
    marker = directory / "shortcuts.json"
    if marker.exists():
        return
    name = Translator(language)("QuizChirp")
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(APP_ROOT / "tools" / "create_shortcuts.ps1"),
             "-ShortcutName", name],
            check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=30,
        )
        marker.write_text(json.dumps({"name": name}, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        logging.getLogger(__name__).exception("Could not create shortcuts; will retry next launch")
