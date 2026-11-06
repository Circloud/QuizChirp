import os
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent


def prepare_data_directory():
    directory = APP_ROOT / "data"
    temporary = directory / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    for name in ("TMP", "TEMP", "TMPDIR"):
        os.environ[name] = str(temporary)
    tempfile.tempdir = str(temporary)
    return directory
