"""Discover or explicitly download a verified runtime without requiring Python tools."""
import hashlib
import json
import os
import platform
import shutil
import ssl
import sys
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

import certifi
from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from openai_codex._runtime_requirements import require_runtime_version

from .engine import RUNTIME_OVERRIDES
from .paths import APP_ROOT, data_directory


class DownloadCancelled(Exception):
    pass


def executable_name():
    return "codex.exe" if sys.platform == "win32" else "codex"


def candidates(saved):
    exe = executable_name()
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
    yield data_directory() / "runtime/codex_cli_bin/bin" / exe
    if not getattr(sys, "frozen", False):
        yield APP_ROOT / ".runtime/codex_cli_bin/bin" / exe


def probe(path):
    with tempfile.TemporaryDirectory(prefix="runtime-check-", ignore_cleanup_errors=True) as home:
        client = CodexClient(CodexConfig(codex_bin=str(path), cwd=str(data_directory()),
            env={"CODEX_HOME": home}, config_overrides=RUNTIME_OVERRIDES))
        timer = threading.Timer(15, client.close)
        timer.daemon = True
        timer.start()
        try:
            client.start()
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


def discover(saved, cancelled):
    seen = set()
    for path in candidates(saved):
        if cancelled.is_set():
            return None
        key = str(path.resolve())
        if key not in seen and check(path):
            return path.resolve()
        seen.add(key)
    return None


def download_spec():
    manifest = json.loads(Path(__file__).with_name("runtime-downloads.json").read_text("utf-8"))
    key = f"{sys.platform}-{platform.machine().lower()}"
    if key not in manifest["platforms"]:
        raise RuntimeError("Unsupported runtime platform")
    return manifest["platforms"][key]


def download(directory, cancelled, progress):
    """Verify the pinned wheel before extracting; publish only a usable runtime."""
    spec = download_spec()
    root = directory / "runtime"
    root.mkdir(parents=True, exist_ok=True)

    def checkpoint():
        if cancelled.is_set():
            raise DownloadCancelled()

    with tempfile.TemporaryDirectory(prefix="download-", dir=root) as temporary:
        staging = Path(temporary)
        archive = staging / "runtime.whl"
        digest = hashlib.sha256()
        received = 0
        checkpoint()
        context = ssl.create_default_context(cafile=certifi.where())
        with urlopen(spec["url"], timeout=15, context=context) as response, archive.open("wb") as output:
            while True:
                checkpoint()
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                received += len(block)
                progress(min(100, received * 100 // spec["size"]))
        checkpoint()
        if received != spec["size"] or digest.hexdigest() != spec["sha256"]:
            raise ValueError("Runtime checksum mismatch")
        progress(None)
        with zipfile.ZipFile(archive) as wheel:
            for entry in wheel.infolist():
                checkpoint()
                relative = PurePosixPath(entry.filename)
                if (relative.is_absolute() or ".." in relative.parts or "\\" in entry.filename
                        or any(":" in part for part in relative.parts)):
                    raise ValueError("Unsafe runtime archive")
                if entry.is_dir() or relative.parts[0] != "codex_cli_bin":
                    continue
                target = staging.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with wheel.open(entry) as source, target.open("wb") as output:
                    while block := source.read(1024 * 1024):
                        checkpoint()
                        output.write(block)
                mode = (entry.external_attr >> 16) & 0o777
                if os.name != "nt":
                    target.chmod(mode or 0o644)
        package = staging / "codex_cli_bin"
        binary = package / "bin" / executable_name()
        if os.name != "nt" and binary.exists():
            binary.chmod(binary.stat().st_mode | 0o111)
        checkpoint()
        if not check(binary):
            raise RuntimeError("Downloaded runtime is incompatible")
        checkpoint()
        destination = root / "codex_cli_bin"
        # This directory belongs exclusively to the downloaded runtime, not user data.
        if destination.exists():
            shutil.rmtree(destination)
        package.replace(destination)
        return destination / "bin" / executable_name()
