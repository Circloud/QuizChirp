"""Resolve a Codex executable before starting the tray; never check login."""
import threading
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex._runtime_requirements import require_runtime_version
from .config import Settings
from .engine import RUNTIME_OVERRIDES
from .i18n import Translator
from .paths import APP_ROOT, prepare_data_directory


def candidates(saved):
    exe = "codex.exe" if sys.platform == "win32" else "codex"
    if saved:
        yield Path(saved).expanduser()
    found = shutil.which(exe)
    if found:
        yield Path(found)
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        yield from sorted((local / "OpenAI/Codex/bin").glob("*/codex.exe"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    else:
        for folder in (Path.home() / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin"),
                       Path("/Applications/Codex.app/Contents/Resources"),
                       Path.home() / "Applications/Codex.app/Contents/Resources"):
            yield folder / exe
    yield APP_ROOT / ".runtime/codex_cli_bin/bin" / exe


def probe(path):
    # Disposable home prevents touching either application's credentials/history.
    # Windows helpers can briefly retain handles after the SDK process exits.
    # Cleanup failure must not turn a successful handshake into incompatibility.
    with tempfile.TemporaryDirectory(prefix="runtime-check-", ignore_cleanup_errors=True) as home:
        client = CodexClient(CodexConfig(codex_bin=str(path), cwd=str(APP_ROOT),
            env={"CODEX_HOME": home}, config_overrides=RUNTIME_OVERRIDES))
        client.start()
        timer = threading.Timer(15, client.close)
        timer.daemon = True
        timer.start()
        try:
            client.initialize()
            require_runtime_version(client._runtime_version)
        finally:
            timer.cancel()
            client.close()


def check(path):
    if not path.is_file() or (os.name != "nt" and not os.access(path, os.X_OK)):
        return False
    try:
        probe(path.resolve())
        return True
    except Exception:
        return False


def download():
    uv = os.environ.get("QUIZCHIRP_UV") or shutil.which("uv")
    if not uv:
        raise RuntimeError("uv")
    subprocess.run([uv, "pip", "install", "--python", sys.executable,
        "--target", str(APP_ROOT / ".runtime"), "--no-deps", "--no-cache",
        f"openai-codex-cli-bin=={version('openai-codex')}"], check=True)
    exe = "codex.exe" if sys.platform == "win32" else "codex"
    return APP_ROOT / ".runtime/codex_cli_bin/bin" / exe


def main():
    directory = prepare_data_directory()
    settings = Settings.load(directory)
    text = Translator(settings.language)
    print(text("Checking Codex runtime..."), flush=True)
    seen = set()
    for path in candidates(settings.codex_bin):
        key = str(path.resolve())
        if key not in seen and check(path):
            settings.codex_bin = key
            settings.save(directory)
            return 0
        seen.add(key)
    while True:
        print(text("No compatible Codex runtime found."))
        print(text("1. Download into the project (about 450 MB)"))
        print(text("2. Enter the path to {exe}").format(
            exe="codex.exe" if sys.platform == "win32" else "codex"))
        print(text("3. Exit"))
        choice = input(text("Choose: ")).strip()
        if choice == "3":
            return 1
        if choice == "1":
            print(text("Downloading Codex runtime..."), flush=True)
            try:
                path = download()
            except (OSError, RuntimeError, subprocess.CalledProcessError):
                print(text("Download failed. Check your connection and try again."))
                continue
        elif choice == "2":
            path = Path(input(text("Executable path: ")).strip().strip('\"').strip("'")).expanduser()
        else:
            print(text("Enter 1, 2, or 3."))
            continue
        if check(path):
            settings.codex_bin = str(path.resolve())
            settings.save(directory)
            return 0
        print(text("Cannot use this runtime. Check the path and version, or download a compatible copy."))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(1)
