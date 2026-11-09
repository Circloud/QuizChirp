"""Build the current platform's portable ZIP: uv run --group build python tools/build.py."""
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    if sys.platform not in ('win32', 'darwin'):
        raise SystemExit('Build on Windows or macOS.')
    lock = tomllib.loads((ROOT / 'uv.lock').read_text('utf-8'))
    runtime = next(p for p in lock['package'] if p['name'] == 'openai-codex-cli-bin')
    manifest = json.loads((ROOT / 'quizchirp/runtime-downloads.json').read_text('utf-8'))
    if manifest['version'] != runtime['version']:
        raise SystemExit('Update runtime-downloads.json to match uv.lock before building.')
    for entry in manifest['platforms'].values():
        if not any(w['url'] == entry['url'] and w['hash'] == 'sha256:' + entry['sha256']
                   and w['size'] == entry['size'] for w in runtime['wheels']):
            raise SystemExit('Runtime download metadata does not match uv.lock.')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', 'QuizChirp.spec'],
                   cwd=ROOT, check=True)
    target = ROOT / 'dist'
    machine = platform.machine().lower()
    arch = 'x64' if machine in ('amd64', 'x86_64') else machine
    name = f"QuizChirp-{'macOS' if sys.platform == 'darwin' else 'Windows'}-{arch}"
    if sys.platform == 'darwin':
        # ditto preserves .app symlinks and executable permissions.
        archive = target / (name + '.zip')
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(target / 'QuizChirp.app'), str(archive)], check=True)
    else:
        archive = Path(shutil.make_archive(str(target / name), 'zip', target, 'QuizChirp'))
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'Created {archive} ({archive.stat().st_size / 1024 / 1024:.1f} MiB)')


if __name__ == '__main__':
    main()
