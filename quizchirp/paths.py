import os
import sys
import tempfile
from pathlib import Path

APP_ROOT = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent)


def data_directory():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/QuizChirp"
    return APP_ROOT / "data"


def prepare_data_directory():
    directory = data_directory()
    temporary = directory / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    for name in ("TMP", "TEMP", "TMPDIR"):
        os.environ[name] = str(temporary)
    tempfile.tempdir = str(temporary)
    return directory
