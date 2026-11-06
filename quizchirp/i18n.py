import ctypes
import json
import locale
import sys
from pathlib import Path


def system_language():
    language = ""
    try:
        if sys.platform == "win32":
            language = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        elif sys.platform == "darwin":
            from Foundation import NSLocale
            preferred = NSLocale.preferredLanguages()
            language = str(preferred[0]) if preferred else ""
        else:
            language = locale.getlocale()[0] or ""
    except (AttributeError, ImportError, OSError, ValueError):
        pass
    return "zh-CN" if language.lower().startswith("zh") else "en"


class Translator:
    def __init__(self, language):
        self.messages = {}
        if language == "zh-CN":
            path = Path(__file__).with_name("locales") / "zh-CN.json"
            self.messages = json.loads(path.read_text("utf-8"))

    def __call__(self, text):
        return self.messages.get(text, text)
